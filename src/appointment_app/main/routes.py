from datetime import datetime, time, timedelta
from collections import defaultdict
import time as time_module

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    stream_with_context,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import or_

from ..extensions import db
from ..models import Appointment, Availability, CompanyProfile
from ..notifications import (
    send_appointment_confirmation,
    send_appointment_status_update,
    send_manual_reminder_for_appointment,
)


main_bp = Blueprint("main", __name__)
ALLOWED_APPOINTMENT_STATUSES = {
    Appointment.STATUS_PENDING,
    Appointment.STATUS_REPORTED,
    Appointment.STATUS_CONFIRMED,
    Appointment.STATUS_CANCELLED,
    Appointment.STATUS_PAID,
}
STATUS_ORDER = [
    Appointment.STATUS_PENDING,
    Appointment.STATUS_REPORTED,
    Appointment.STATUS_CONFIRMED,
    Appointment.STATUS_PAID,
    Appointment.STATUS_CANCELLED,
]
STATUS_LABELS = {
    Appointment.STATUS_PENDING: "Pending",
    Appointment.STATUS_REPORTED: "Reported",
    Appointment.STATUS_CONFIRMED: "Confirmed",
    Appointment.STATUS_PAID: "Paid",
    Appointment.STATUS_CANCELLED: "Cancelled",
}
STATUS_COLORS = {
    Appointment.STATUS_PENDING: "amber",
    Appointment.STATUS_REPORTED: "indigo",
    Appointment.STATUS_CONFIRMED: "emerald",
    Appointment.STATUS_PAID: "teal",
    Appointment.STATUS_CANCELLED: "rose",
}
WEEKDAY_LABELS = {
    0: "Lundi",
    1: "Mardi",
    2: "Mercredi",
    3: "Jeudi",
    4: "Vendredi",
    5: "Samedi",
    6: "Dimanche",
}
SLOT_MINUTES = 30


def _parse_iso_datetime(raw_value: str) -> datetime | None:
    """Convertit une date ISO (avec/sans Z) en datetime naive."""
    if not raw_value:
        return None

    normalized = raw_value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    # FullCalendar envoie souvent des dates timezone-aware: on passe en naive locale.
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _build_calendar_events(company: CompanyProfile, window_start: datetime, window_end: datetime):
    """Construit les evenements FullCalendar (disponible/occupe) sur la fenetre demandee."""
    events = []
    step = timedelta(minutes=SLOT_MINUTES)

    availabilities = Availability.query.filter_by(company_id=company.id, is_active=True).all()
    availability_by_day = {}
    for slot in availabilities:
        availability_by_day.setdefault(slot.weekday, []).append(slot)

    booked_appointments = Appointment.query.filter(
        Appointment.company_id == company.id,
        Appointment.start_at >= window_start,
        Appointment.start_at < window_end,
        Appointment.status != Appointment.STATUS_CANCELLED,
    ).all()
    booked_starts = {appt.start_at for appt in booked_appointments}

    current_date = window_start.date()
    last_date = window_end.date()
    while current_date <= last_date:
        day_slots = availability_by_day.get(current_date.weekday(), [])
        for slot in day_slots:
            cursor = datetime.combine(current_date, slot.start_time)
            slot_end = datetime.combine(current_date, slot.end_time)
            while cursor < slot_end:
                if window_start <= cursor < window_end:
                    end_cursor = cursor + step
                    is_booked = cursor in booked_starts
                    events.append(
                        {
                            "title": "Reserve" if is_booked else "Disponible",
                            "start": cursor.isoformat(),
                            "end": end_cursor.isoformat(),
                            "color": "#d9534f" if is_booked else "#2f9e6f",
                            "extendedProps": {"available": not is_booked},
                        }
                    )
                cursor += step
        current_date += timedelta(days=1)

    return events


def _is_within_company_availability(company_id: int, dt: datetime) -> bool:
    """Verifie si un datetime tombe dans une plage de disponibilite active."""
    weekday = dt.weekday()
    current_time = dt.time()

    slots = Availability.query.filter_by(
        company_id=company_id, weekday=weekday, is_active=True
    ).all()
    for slot in slots:
        if slot.start_time <= current_time < slot.end_time:
            return True
    return False


def _get_client_appointment_for_current_user(appointment_id: int) -> Appointment | None:
    """
    Retourne un rendez-vous accessible au client courant.
    Compatibilite:
    - nouveaux rendez-vous relies par client_user_id
    - anciens rendez-vous relies seulement par customer_email
    """
    if not current_user.is_authenticated:
        return None

    return Appointment.query.filter(
        Appointment.id == appointment_id,
        or_(
            Appointment.client_user_id == current_user.id,
            Appointment.customer_email == current_user.email,
        ),
    ).first()


def _group_appointments_by_status(appointments: list[Appointment]) -> dict[str, list[Appointment]]:
    """
    Regroupe les rendez-vous par statut en conservant l'ordre de colonnes souhaité.
    """
    grouped_map = defaultdict(list)
    for appointment in appointments:
        grouped_map[appointment.status].append(appointment)

    return {status: grouped_map.get(status, []) for status in STATUS_ORDER}


def _build_appointments_signature(appointments: list[Appointment]) -> str:
    """
    Construit une signature d'etat pour detecter les changements sans WebSocket.
    Si la signature change, l'UI peut se rafraichir automatiquement.
    """
    chunks: list[str] = []
    for appointment in appointments:
        chunks.append(
            ":".join(
                [
                    str(appointment.id),
                    appointment.status,
                    appointment.start_at.isoformat(),
                    appointment.reminder_sent_at.isoformat()
                    if appointment.reminder_sent_at
                    else "",
                ]
            )
        )
    return "|".join(chunks)


def _company_appointments_signature(company_id: int) -> str:
    """Signature des rendez-vous d'une entreprise pour flux temps reel."""
    appointments = (
        Appointment.query.filter_by(company_id=company_id)
        .order_by(Appointment.id.asc())
        .all()
    )
    return _build_appointments_signature(appointments)


def _client_appointments_signature(user_id: int, user_email: str) -> str:
    """Signature des rendez-vous visibles par le client connecte."""
    appointments = (
        Appointment.query.filter(
            or_(
                Appointment.client_user_id == user_id,
                Appointment.customer_email == user_email,
            )
        )
        .order_by(Appointment.id.asc())
        .all()
    )
    return _build_appointments_signature(appointments)


@main_bp.route("/")
def home():
    return render_template("main/home.html")


@main_bp.route("/companies")
@login_required
def companies():
    """
    Catalogue des entreprises actives.
    Le client choisit d'abord l'entreprise avant la reservation.
    """
    if current_user.role != "client":
        abort(403)

    companies_list = (
        CompanyProfile.query.filter_by(is_active=True)
        .order_by(CompanyProfile.company_name.asc())
        .all()
    )
    return render_template("main/companies.html", companies=companies_list)


@main_bp.route("/dashboard")
@login_required
def dashboard():
    company_booking_link = None
    company_appointments = []
    grouped_company_appointments = {}
    company_availabilities = []
    now_utc = datetime.utcnow()
    if current_user.role == "company" and current_user.company_profile:
        # Lien public a partager avec les clients de cette entreprise.
        company_booking_link = url_for(
            "main.company_public_page",
            company_slug=current_user.company_profile.public_slug,
            _external=True,
        )
        # Liste des rendez-vous de l'entreprise pour suivi et changement de statut.
        # L'entreprise voit tous ses rendez-vous, classes ensuite par blocs de statut.
        company_appointments = Appointment.query.filter_by(
            company_id=current_user.company_profile.id
        ).order_by(Appointment.start_at.asc()).all()
        reminder_resend_window = timedelta(hours=1)
        for appointment in company_appointments:
            time_to_start = appointment.start_at - now_utc
            appointment.can_send_manual_reminder = (
                appointment.reminder_sent_at is None
                or timedelta(0) <= time_to_start <= reminder_resend_window
            )
        grouped_company_appointments = _group_appointments_by_status(company_appointments)
        company_availabilities = Availability.query.filter_by(
            company_id=current_user.company_profile.id
        ).order_by(Availability.weekday.asc(), Availability.start_time.asc()).all()

    return render_template(
        "main/dashboard.html",
        user=current_user,
        company_booking_link=company_booking_link,
        company_appointments=company_appointments,
        grouped_company_appointments=grouped_company_appointments,
        company_availabilities=company_availabilities,
        status_choices=sorted(ALLOWED_APPOINTMENT_STATUSES),
        status_order=STATUS_ORDER,
        status_labels=STATUS_LABELS,
        status_colors=STATUS_COLORS,
        weekday_labels=WEEKDAY_LABELS,
        now_utc=now_utc,
    )


@main_bp.route("/c/<string:company_slug>", methods=["GET", "POST"])
def company_public_page(company_slug: str):
    """Page publique d'une entreprise (point d'entree client)."""
    company = CompanyProfile.query.filter_by(public_slug=company_slug, is_active=True).first()
    if company is None:
        abort(404)

    if request.method == "POST":
        customer_name = request.form.get("customer_name", "").strip()
        customer_email = request.form.get("customer_email", "").strip().lower()
        start_at_raw = request.form.get("start_at", "").strip()
        notes = request.form.get("notes", "").strip()

        if not customer_name or not customer_email or not start_at_raw:
            flash("Nom, email et date/heure sont obligatoires.", "error")
            return render_template(
                "main/company_public_page.html",
                company=company,
                weekday_labels=WEEKDAY_LABELS,
                calendar_events_url=url_for("main.company_calendar_events", company_slug=company_slug),
            )

        try:
            start_at = datetime.strptime(start_at_raw, "%Y-%m-%dT%H:%M")
        except ValueError:
            flash("Format de date invalide.", "error")
            return render_template(
                "main/company_public_page.html",
                company=company,
                weekday_labels=WEEKDAY_LABELS,
                calendar_events_url=url_for("main.company_calendar_events", company_slug=company_slug),
            )

        # Regle simple: pas de reservation dans le passe.
        if start_at <= datetime.utcnow():
            flash("Choisis une date/heure future.", "error")
            return render_template(
                "main/company_public_page.html",
                company=company,
                weekday_labels=WEEKDAY_LABELS,
                calendar_events_url=url_for("main.company_calendar_events", company_slug=company_slug),
            )

        # La reservation doit tomber dans les disponibilites hebdomadaires configurees.
        if not _is_within_company_availability(company.id, start_at):
            flash("Ce creneau est hors disponibilites de l'entreprise.", "error")
            return render_template(
                "main/company_public_page.html",
                company=company,
                weekday_labels=WEEKDAY_LABELS,
                calendar_events_url=url_for("main.company_calendar_events", company_slug=company_slug),
            )

        # Conflit basique: un rendez-vous actif par entreprise et heure exacte.
        existing_slot = Appointment.query.filter(
            Appointment.company_id == company.id,
            Appointment.start_at == start_at,
            Appointment.status != Appointment.STATUS_CANCELLED,
        ).first()
        if existing_slot:
            flash("Ce creneau est deja reserve. Choisis un autre horaire.", "error")
            return render_template(
                "main/company_public_page.html",
                company=company,
                weekday_labels=WEEKDAY_LABELS,
                calendar_events_url=url_for("main.company_calendar_events", company_slug=company_slug),
            )

        appointment = Appointment(
            company_id=company.id,
            client_user_id=current_user.id
            if current_user.is_authenticated and current_user.role == "client"
            else None,
            customer_name=customer_name,
            customer_email=customer_email,
            start_at=start_at,
            notes=notes or None,
            status=Appointment.STATUS_PENDING,
        )
        db.session.add(appointment)
        db.session.commit()

        # Envoyer l'email de confirmation au client
        send_appointment_confirmation(appointment)

        flash("Rendez-vous enregistre. L'entreprise confirmera le statut.", "success")
        return redirect(url_for("main.company_public_page", company_slug=company_slug))

    return render_template(
        "main/company_public_page.html",
        company=company,
        weekday_labels=WEEKDAY_LABELS,
        calendar_events_url=url_for("main.company_calendar_events", company_slug=company_slug),
    )


@main_bp.route("/c/<string:company_slug>/calendar-events")
def company_calendar_events(company_slug: str):
    """Retourne les evenements calendar (disponible/occupe) pour FullCalendar."""
    company = CompanyProfile.query.filter_by(public_slug=company_slug, is_active=True).first()
    if company is None:
        abort(404)

    window_start = _parse_iso_datetime(request.args.get("start", ""))
    window_end = _parse_iso_datetime(request.args.get("end", ""))
    if window_start is None or window_end is None:
        # Fenetre par defaut: semaine courante si FullCalendar n'envoie rien.
        now = datetime.utcnow()
        monday = datetime.combine((now - timedelta(days=now.weekday())).date(), time(0, 0))
        window_start = monday
        window_end = monday + timedelta(days=7)

    events = _build_calendar_events(company=company, window_start=window_start, window_end=window_end)
    return jsonify(events)


@main_bp.route("/stream/company-appointments")
@login_required
def stream_company_appointments():
    """
    Flux SSE pour dashboard entreprise.
    Le serveur envoie 'update' uniquement si les rendez-vous changent.
    """
    if current_user.role != "company" or not current_user.company_profile:
        abort(403)

    company_id = current_user.company_profile.id

    @stream_with_context
    def event_stream():
        # Initialisation: baseline courante pour eviter un refresh en boucle au premier event.
        last_signature = _company_appointments_signature(company_id)

        # On boucle sur une fenetre limitee puis le navigateur se reconnecte.
        for _ in range(90):  # ~180 secondes (2s * 90)
            current_signature = _company_appointments_signature(company_id)
            if current_signature != last_signature:
                last_signature = current_signature
                yield "event: update\ndata: changed\n\n"
            else:
                # Heartbeat pour garder la connexion vivante.
                yield "event: ping\ndata: keepalive\n\n"
            time_module.sleep(2)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@main_bp.route("/my-appointments")
@login_required
def my_appointments():
    """Espace client: consulter ses rendez-vous et effectuer des actions."""
    if current_user.role != "client":
        abort(403)

    appointments = Appointment.query.filter(
        or_(
            Appointment.client_user_id == current_user.id,
            Appointment.customer_email == current_user.email,
        )
    ).order_by(Appointment.start_at.asc()).all()
    grouped_appointments = _group_appointments_by_status(appointments)

    return render_template(
        "main/my_appointments.html",
        appointments=appointments,
        grouped_appointments=grouped_appointments,
        status_order=STATUS_ORDER,
        status_labels=STATUS_LABELS,
        status_colors=STATUS_COLORS,
        auto_refresh_seconds=current_app.config["UI_AUTO_REFRESH_SECONDS"],
    )


@main_bp.route("/stream/my-appointments")
@login_required
def stream_my_appointments():
    """
    Flux SSE pour l'espace client.
    Permet une mise a jour automatique du statut sans action manuelle.
    """
    if current_user.role != "client":
        abort(403)

    user_id = current_user.id
    user_email = current_user.email

    @stream_with_context
    def event_stream():
        # Initialisation: baseline courante pour eviter un refresh en boucle au premier event.
        last_signature = _client_appointments_signature(user_id, user_email)

        # Fenetre limitee; le navigateur EventSource reconnecte automatiquement.
        for _ in range(90):  # ~180 secondes (2s * 90)
            current_signature = _client_appointments_signature(user_id, user_email)
            if current_signature != last_signature:
                last_signature = current_signature
                yield "event: update\ndata: changed\n\n"
            else:
                # Heartbeat pour eviter les timeouts intermediaires.
                yield "event: ping\ndata: keepalive\n\n"
            time_module.sleep(2)

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@main_bp.route("/my-appointments/<int:appointment_id>/cancel", methods=["POST"])
@login_required
def cancel_my_appointment(appointment_id: int):
    """Annulation client d'un rendez-vous lui appartenant."""
    if current_user.role != "client":
        abort(403)

    appointment = _get_client_appointment_for_current_user(appointment_id)
    if appointment is None:
        abort(404)

    # Regle metier: un rendez-vous paye ne peut plus etre modifie.
    if appointment.status == Appointment.STATUS_PAID:
        flash("Rendez-vous paye: annulation impossible.", "warning")
        return redirect(url_for("main.my_appointments"))

    if appointment.status == Appointment.STATUS_CANCELLED:
        flash("Ce rendez-vous est deja annule.", "warning")
        return redirect(url_for("main.my_appointments"))

    appointment.status = Appointment.STATUS_CANCELLED
    db.session.commit()
    flash("Rendez-vous annule.", "success")
    return redirect(url_for("main.my_appointments"))


@main_bp.route("/my-appointments/<int:appointment_id>/reschedule", methods=["POST"])
@login_required
def reschedule_my_appointment(appointment_id: int):
    """Report client d'un rendez-vous avec validation disponibilite + conflit."""
    if current_user.role != "client":
        abort(403)

    appointment = _get_client_appointment_for_current_user(appointment_id)
    if appointment is None:
        abort(404)

    # Regle metier: un rendez-vous paye ne peut plus etre modifie.
    if appointment.status == Appointment.STATUS_PAID:
        flash("Rendez-vous paye: report impossible.", "warning")
        return redirect(url_for("main.my_appointments"))

    new_start_raw = request.form.get("start_at", "").strip()
    try:
        new_start_at = datetime.strptime(new_start_raw, "%Y-%m-%dT%H:%M")
    except ValueError:
        flash("Format de date invalide.", "error")
        return redirect(url_for("main.my_appointments"))

    if new_start_at <= datetime.utcnow():
        flash("Choisis une date/heure future.", "error")
        return redirect(url_for("main.my_appointments"))

    if not _is_within_company_availability(appointment.company_id, new_start_at):
        flash("Ce nouveau creneau est hors disponibilites de l'entreprise.", "error")
        return redirect(url_for("main.my_appointments"))

    conflicting = Appointment.query.filter(
        Appointment.company_id == appointment.company_id,
        Appointment.start_at == new_start_at,
        Appointment.status != Appointment.STATUS_CANCELLED,
        Appointment.id != appointment.id,
    ).first()
    if conflicting:
        flash("Ce creneau est deja reserve. Choisis un autre horaire.", "error")
        return redirect(url_for("main.my_appointments"))

    appointment.start_at = new_start_at
    # Un report client passe dans le bloc 'reported' pour revue entreprise.
    appointment.status = Appointment.STATUS_REPORTED
    db.session.commit()

    flash("Rendez-vous reporte. Statut passe a reported.", "success")
    return redirect(url_for("main.my_appointments"))


@main_bp.route("/company/availabilities", methods=["POST"])
@login_required
def create_availability():
    """Ajoute une disponibilite hebdomadaire pour l'entreprise connectee."""
    if current_user.role != "company" or not current_user.company_profile:
        abort(403)

    weekday_raw = request.form.get("weekday", "").strip()
    start_time_raw = request.form.get("start_time", "").strip()
    end_time_raw = request.form.get("end_time", "").strip()

    try:
        weekday = int(weekday_raw)
    except ValueError:
        flash("Jour invalide.", "error")
        return redirect(url_for("main.dashboard"))

    if weekday not in WEEKDAY_LABELS:
        flash("Jour invalide.", "error")
        return redirect(url_for("main.dashboard"))

    try:
        start_time = datetime.strptime(start_time_raw, "%H:%M").time()
        end_time = datetime.strptime(end_time_raw, "%H:%M").time()
    except ValueError:
        flash("Format d'heure invalide.", "error")
        return redirect(url_for("main.dashboard"))

    if start_time >= end_time:
        flash("L'heure de debut doit etre avant l'heure de fin.", "error")
        return redirect(url_for("main.dashboard"))

    # Evite les doublons exacts de plage.
    duplicate = Availability.query.filter_by(
        company_id=current_user.company_profile.id,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
    ).first()
    if duplicate:
        flash("Cette disponibilite existe deja.", "warning")
        return redirect(url_for("main.dashboard"))

    availability = Availability(
        company_id=current_user.company_profile.id,
        weekday=weekday,
        start_time=start_time,
        end_time=end_time,
        is_active=True,
    )
    db.session.add(availability)
    db.session.commit()

    flash("Disponibilite ajoutee.", "success")
    return redirect(url_for("main.dashboard"))


@main_bp.route("/company/availabilities/<int:availability_id>/delete", methods=["POST"])
@login_required
def delete_availability(availability_id: int):
    """Supprime une disponibilite appartenant a l'entreprise connectee."""
    if current_user.role != "company" or not current_user.company_profile:
        abort(403)

    availability = Availability.query.filter_by(
        id=availability_id, company_id=current_user.company_profile.id
    ).first()
    if availability is None:
        abort(404)

    db.session.delete(availability)
    db.session.commit()
    flash("Disponibilite supprimee.", "success")
    return redirect(url_for("main.dashboard"))


@main_bp.route("/company/appointments/<int:appointment_id>/status", methods=["POST"])
@login_required
def update_appointment_status(appointment_id: int):
    """Permet a l'entreprise de modifier le statut d'un rendez-vous."""
    if current_user.role != "company" or not current_user.company_profile:
        abort(403)

    new_status = request.form.get("status", "").strip().lower()
    if new_status not in ALLOWED_APPOINTMENT_STATUSES:
        flash("Statut invalide.", "error")
        return redirect(url_for("main.dashboard"))

    appointment = Appointment.query.filter_by(
        id=appointment_id, company_id=current_user.company_profile.id
    ).first()
    if appointment is None:
        abort(404)

    # Regle metier: une fois paye, le rendez-vous est verrouille.
    if appointment.status == Appointment.STATUS_PAID:
        flash("Statut verrouille: un rendez-vous paye ne peut plus changer.", "warning")
        return redirect(url_for("main.dashboard"))

    appointment.status = new_status
    db.session.commit()
    send_appointment_status_update(appointment)

    flash("Statut du rendez-vous mis a jour.", "success")
    return redirect(url_for("main.dashboard"))


@main_bp.route("/company/appointments/<int:appointment_id>/send-mail", methods=["POST"])
@login_required
def send_appointment_mail(appointment_id: int):
    """
    Envoi manuel d'un rappel email par l'entreprise.
    Si un rappel existe deja, le renvoi est autorise dans la derniere heure
    avant le rendez-vous.
    """
    if current_user.role != "company" or not current_user.company_profile:
        abort(403)

    appointment = Appointment.query.filter_by(
        id=appointment_id, company_id=current_user.company_profile.id
    ).first()
    if appointment is None:
        abort(404)

    success, message = send_manual_reminder_for_appointment(appointment)
    flash(message, "success" if success else "error")
    return redirect(url_for("main.dashboard"))
