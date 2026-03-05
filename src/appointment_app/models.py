from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


class User(UserMixin, db.Model):
    """Utilisateur de la plateforme (client ou entreprise)."""

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(20), nullable=False, default="client")
    oauth_accounts = db.relationship(
        "OAuthAccount", back_populates="user", cascade="all, delete-orphan"
    )
    company_profile = db.relationship(
        "CompanyProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    client_appointments = db.relationship(
        "Appointment",
        back_populates="client_user",
        foreign_keys="Appointment.client_user_id",
    )

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

class OAuthAccount(db.Model):
    """Lien entre un utilisateur local et un fournisseur OAuth."""

    id = db.Column(db.Integer, primary_key=True)
    provider = db.Column(db.String(50), nullable=False)
    provider_user_id = db.Column(db.String(255), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    user = db.relationship("User", back_populates="oauth_accounts")

    __table_args__ = (
        db.UniqueConstraint("provider", "provider_user_id", name="uq_provider_user"),
    )


class CompanyProfile(db.Model):
    """Profil public d'une entreprise avec URL partageable."""

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)
    company_name = db.Column(db.String(140), nullable=False)
    public_slug = db.Column(db.String(160), nullable=False, unique=True, index=True)
    booking_page_title = db.Column(db.String(180), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    user = db.relationship("User", back_populates="company_profile")
    appointments = db.relationship(
        "Appointment",
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="Appointment.start_at.desc()",
    )
    availabilities = db.relationship(
        "Availability",
        back_populates="company",
        cascade="all, delete-orphan",
        order_by="Availability.weekday.asc(), Availability.start_time.asc()",
    )


class Appointment(db.Model):
    """Rendez-vous reserve par un client pour une entreprise."""

    STATUS_PENDING = "pending"
    STATUS_REPORTED = "reported"
    STATUS_CONFIRMED = "confirmed"
    STATUS_CANCELLED = "cancelled"
    STATUS_PAID = "paid"

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("company_profile.id"), nullable=False)
    client_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    customer_name = db.Column(db.String(140), nullable=False)
    customer_email = db.Column(db.String(255), nullable=False, index=True)
    start_at = db.Column(db.DateTime, nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default=STATUS_PENDING, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    reminder_sent_at = db.Column(db.DateTime, nullable=True, index=True)

    company = db.relationship("CompanyProfile", back_populates="appointments")
    client_user = db.relationship(
        "User", back_populates="client_appointments", foreign_keys=[client_user_id]
    )
    reminder_logs = db.relationship(
        "ReminderLog", back_populates="appointment", cascade="all, delete-orphan"
    )


class Availability(db.Model):
    """Disponibilite hebdomadaire d'une entreprise (jour + plage horaire)."""

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey("company_profile.id"), nullable=False)
    weekday = db.Column(db.Integer, nullable=False, index=True)  # 0=lundi, 6=dimanche
    start_time = db.Column(db.Time, nullable=False)
    end_time = db.Column(db.Time, nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    company = db.relationship("CompanyProfile", back_populates="availabilities")

    __table_args__ = (
        db.CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_availability_weekday"),
        db.CheckConstraint("start_time < end_time", name="ck_availability_time_range"),
    )


class ReminderLog(db.Model):
    """Journal d'envoi des rappels email pour audit/debug."""

    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"

    id = db.Column(db.Integer, primary_key=True)
    appointment_id = db.Column(db.Integer, db.ForeignKey("appointment.id"), nullable=False, index=True)
    recipient_email = db.Column(db.String(255), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, index=True)
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    appointment = db.relationship("Appointment", back_populates="reminder_logs")


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))
