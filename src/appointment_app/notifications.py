from datetime import datetime, timedelta

from flask import current_app, render_template
from flask_mail import Message

from .extensions import db, mail
from .models import Appointment, ReminderLog


def _build_and_send_email(
    subject: str,
    recipient: str,
    text_body: str,
    html_body: str | None = None,
) -> bool:
    """
    Envoie un email via Flask-Mail.
    Retourne True si succès, False sinon.
    """
    if not current_app.config.get("MAIL_ENABLED"):
        current_app.logger.warning("MAIL_ENABLED=false; email not sent to %s", recipient)
        return False

    try:
        msg = Message(
            subject=subject,
            recipients=[recipient],
            body=text_body,
            html=html_body,
        )
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.exception("Failed to send email to %s: %s", recipient, str(e))
        return False


def send_appointment_confirmation(appointment: Appointment) -> bool:
    """
    Envoie un email de confirmation au client après création d'un rendez-vous.
    """
    company_name = (
        appointment.company.company_name if appointment.company else "votre entreprise"
    )
    start_at_str = appointment.start_at.strftime("%d/%m/%Y à %H:%M")

    subject = f"Confirmation - Rendez-vous chez {company_name}"
    text_body = "\n".join(
        [
            f"Bonjour {appointment.customer_name},",
            "",
            "Votre rendez-vous a bien été enregistré:",
            f"Entreprise: {company_name}",
            f"Date/Heure: {start_at_str}",
            "Statut: En attente de confirmation",
            "",
            "L'entreprise va confirmer votre rendez-vous dans les meilleurs délais.",
            "Vous recevrez un email de confirmation dès que possible.",
            "",
            "Cordialement,",
            "Notre système de gestion de rendez-vous",
        ]
    )

    html_body = render_template(
        "emails/confirmation.html",
        customer_name=appointment.customer_name,
        company_name=company_name,
        start_at_str=start_at_str,
    )

    return _build_and_send_email(
        subject=subject,
        recipient=appointment.customer_email,
        text_body=text_body,
        html_body=html_body,
    )


def send_appointment_status_update(appointment: Appointment) -> bool:
    """
    Envoie un email de mise à jour de statut au client.
    """
    company_name = (
        appointment.company.company_name if appointment.company else "votre entreprise"
    )
    start_at_str = appointment.start_at.strftime("%d/%m/%Y à %H:%M")

    status_messages = {
        Appointment.STATUS_CONFIRMED: "confirmé",
        Appointment.STATUS_CANCELLED: "annulé",
        Appointment.STATUS_PAID: "payé",
        Appointment.STATUS_PENDING: "en attente",
        Appointment.STATUS_REPORTED: "report demandé",
    }
    status_text = status_messages.get(appointment.status, appointment.status)

    subject = f"Mise à jour - Rendez-vous chez {company_name}"
    text_body = "\n".join(
        [
            f"Bonjour {appointment.customer_name},",
            "",
            "Votre rendez-vous a été mis à jour:",
            f"Entreprise: {company_name}",
            f"Date/Heure: {start_at_str}",
            f"Nouveau statut: {status_text}",
            "",
            "Cordialement,",
            "Notre système de gestion de rendez-vous",
        ]
    )

    html_body = render_template(
        "emails/status_update.html",
        customer_name=appointment.customer_name,
        company_name=company_name,
        start_at_str=start_at_str,
        status=status_text,
    )

    return _build_and_send_email(
        subject=subject,
        recipient=appointment.customer_email,
        text_body=text_body,
        html_body=html_body,
    )


def _build_reminder_email(appointment: Appointment) -> dict:
    """Construit les variables pour l'email de rappel d'un rendez-vous."""
    company_name = appointment.company.company_name if appointment.company else "votre entreprise"
    start_at_str = appointment.start_at.strftime("%d/%m/%Y à %H:%M")

    return {
        "subject": f"Rappel rendez-vous - {company_name}",
        "recipient": appointment.customer_email,
        "text_body": "\n".join(
            [
                f"Bonjour {appointment.customer_name},",
                "",
                "Ceci est un rappel de votre rendez-vous:",
                f"Entreprise: {company_name}",
                f"Date/heure: {start_at_str}",
                f"Statut: {appointment.status}",
                "",
                "Merci.",
            ]
        ),
        "html_body": render_template(
            "emails/reminder.html",
            customer_name=appointment.customer_name,
            company_name=company_name,
            start_at_str=start_at_str,
            status=appointment.status,
        ),
    }


def _log_reminder_attempt(
    appointment: Appointment, status: str, error_message: str | None = None
) -> None:
    """Trace chaque tentative d'envoi de rappel dans la base."""
    db.session.add(
        ReminderLog(
            appointment_id=appointment.id,
            recipient_email=appointment.customer_email,
            status=status,
            error_message=error_message,
        )
    )


def send_upcoming_appointment_reminders(hours_ahead: int = 24, dry_run: bool = False) -> dict:
    """
    Envoie les rappels pour les rendez-vous imminents non annulés.
    Le champ `reminder_sent_at` évite les envois multiples.
    """
    now = datetime.utcnow()
    window_end = now + timedelta(hours=hours_ahead)

    appointments = Appointment.query.filter(
        Appointment.start_at >= now,
        Appointment.start_at <= window_end,
        Appointment.status != Appointment.STATUS_CANCELLED,
        Appointment.reminder_sent_at.is_(None),
    ).all()

    sent_count = 0
    failed_count = 0
    skipped_count = 0

    for appointment in appointments:
        if dry_run:
            current_app.logger.info(
                "[DRY-RUN] reminder candidate id=%s email=%s start_at=%s",
                appointment.id,
                appointment.customer_email,
                appointment.start_at,
            )
            continue

        if not current_app.config.get("MAIL_ENABLED"):
            current_app.logger.warning(
                "MAIL_ENABLED=false; skip reminder for appointment id=%s", appointment.id
            )
            skipped_count += 1
            _log_reminder_attempt(appointment, ReminderLog.STATUS_SKIPPED, "MAIL_ENABLED=false")
            continue

        try:
            email_data = _build_reminder_email(appointment)
            success = _build_and_send_email(
                subject=email_data["subject"],
                recipient=email_data["recipient"],
                text_body=email_data["text_body"],
                html_body=email_data["html_body"],
            )
            if success:
                appointment.reminder_sent_at = datetime.utcnow()
                sent_count += 1
                _log_reminder_attempt(appointment, ReminderLog.STATUS_SENT)
            else:
                failed_count += 1
                _log_reminder_attempt(appointment, ReminderLog.STATUS_FAILED, "Mail send failed")
        except Exception as e:
            current_app.logger.exception(
                "Reminder send failed for appointment id=%s", appointment.id
            )
            failed_count += 1
            _log_reminder_attempt(appointment, ReminderLog.STATUS_FAILED, str(e))

    if not dry_run and (sent_count or failed_count or skipped_count):
        db.session.commit()

    return {
        "checked": len(appointments),
        "sent": sent_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "dry_run": dry_run,
    }


def send_manual_reminder_for_appointment(appointment: Appointment) -> tuple[bool, str]:
    """
    Envoie un rappel manuel pour un rendez-vous donne.
    Cette fonction est utilisee par le bouton 'Envoyer le mail' du dashboard entreprise.
    """
    if appointment.status == Appointment.STATUS_CANCELLED:
        return False, "Rendez-vous annule: rappel non envoye."

    if appointment.reminder_sent_at is not None:
        now = datetime.utcnow()
        if appointment.start_at <= now:
            return False, "Rendez-vous deja passe: renvoi du mail non autorise."
        if appointment.start_at - now > timedelta(hours=1):
            return (
                False,
                "Un mail a deja ete envoye. Renvoi possible dans la derniere heure avant le rendez-vous.",
            )

    if not current_app.config.get("MAIL_ENABLED"):
        return False, "MAIL_ENABLED=false. Active l'envoi mail dans .env."

    try:
        email_data = _build_reminder_email(appointment)
        success = _build_and_send_email(
            subject=email_data["subject"],
            recipient=email_data["recipient"],
            text_body=email_data["text_body"],
            html_body=email_data["html_body"],
        )
        if not success:
            _log_reminder_attempt(appointment, ReminderLog.STATUS_FAILED, "Mail send failed")
            db.session.commit()
            return False, "Echec d'envoi du mail (verifie SMTP, identifiants et TLS)."

        appointment.reminder_sent_at = datetime.utcnow()
        _log_reminder_attempt(appointment, ReminderLog.STATUS_SENT)
        db.session.commit()
        return True, "Mail envoye au client."
    except Exception as e:
        current_app.logger.exception(
            "Manual reminder failed for appointment id=%s", appointment.id
        )
        _log_reminder_attempt(appointment, ReminderLog.STATUS_FAILED, str(e))
        db.session.commit()
        return False, f"Erreur technique pendant l'envoi du mail: {e}"
