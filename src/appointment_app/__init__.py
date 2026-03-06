from pathlib import Path
from logging.handlers import RotatingFileHandler
import logging
import secrets

import click
from flask import Flask, abort, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from .auth import auth_bp
from .config import Config
from .extensions import db, login_manager, mail, oauth
from .main import main_bp
from .notifications import send_upcoming_appointment_reminders


def _configure_logging(app: Flask) -> None:
    """Configure des logs fichiers + console sans duplication."""
    log_level_name = str(app.config.get("LOG_LEVEL", "INFO")).upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    log_file = Path(str(app.config.get("LOG_FILE", "instance/logs/app.log")))
    if not log_file.is_absolute():
        log_file = Path(app.root_path).parent.parent / log_file
    log_file.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s in %(module)s: %(message)s",
        "%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(formatter)

    app.logger.handlers.clear()
    app.logger.setLevel(log_level)
    app.logger.addHandler(file_handler)
    app.logger.addHandler(stream_handler)
    app.logger.propagate = False


def _configure_security(app: Flask) -> None:
    """Durcit l'application: proxy, CSRF minimal, headers HTTP."""

    if app.config["SECRET_KEY"] in {"dev-secret-key", "change-this-in-production"}:
        app.logger.warning("SECRET_KEY par defaut detecte. Remplace-le en production.")

    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=app.config["PROXY_FIX_X_FOR"],
        x_proto=app.config["PROXY_FIX_X_PROTO"],
        x_host=app.config["PROXY_FIX_X_HOST"],
        x_port=app.config["PROXY_FIX_X_PORT"],
        x_prefix=app.config["PROXY_FIX_X_PREFIX"],
    )

    def _csrf_token() -> str:
        token = session.get("_csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            session["_csrf_token"] = token
        return token

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": _csrf_token}

    @app.before_request
    def csrf_protect():
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return
        token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
        session_token = session.get("_csrf_token")
        if not token or not session_token or token != session_token:
            abort(400, description="CSRF token missing or invalid.")

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'",
        )
        if request.is_secure:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    # Charger les variables d'environnement depuis .env si présentes (utile en dev/cron).
    try:
        # import local to avoid hard dependency when not needed
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    app.config.from_object(config_class)
    _configure_logging(app)
    _configure_security(app)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)
    mail.init_app(app)

    if app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            server_metadata_url=app.config["GOOGLE_SERVER_METADATA_URL"],
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            client_kwargs={"scope": "openid email profile"},
        )
    if app.config.get("GITHUB_CLIENT_ID") and app.config.get("GITHUB_CLIENT_SECRET"):
        oauth.register(
            name="github",
            client_id=app.config["GITHUB_CLIENT_ID"],
            client_secret=app.config["GITHUB_CLIENT_SECRET"],
            authorize_url=app.config["GITHUB_AUTHORIZE_URL"],
            access_token_url=app.config["GITHUB_ACCESS_TOKEN_URL"],
            api_base_url=app.config["GITHUB_API_BASE_URL"],
            client_kwargs={"scope": "read:user user:email"},
        )
    if app.config.get("FACEBOOK_CLIENT_ID") and app.config.get("FACEBOOK_CLIENT_SECRET"):
        oauth.register(
            name="facebook",
            client_id=app.config["FACEBOOK_CLIENT_ID"],
            client_secret=app.config["FACEBOOK_CLIENT_SECRET"],
            authorize_url=app.config["FACEBOOK_AUTHORIZE_URL"],
            access_token_url=app.config["FACEBOOK_ACCESS_TOKEN_URL"],
            api_base_url=app.config["FACEBOOK_API_BASE_URL"],
            client_kwargs={"scope": "email public_profile"},
        )
    if app.config.get("LINKEDIN_CLIENT_ID") and app.config.get("LINKEDIN_CLIENT_SECRET"):
        oauth.register(
            name="linkedin",
            client_id=app.config["LINKEDIN_CLIENT_ID"],
            client_secret=app.config["LINKEDIN_CLIENT_SECRET"],
            authorize_url=app.config["LINKEDIN_AUTHORIZE_URL"],
            access_token_url=app.config["LINKEDIN_ACCESS_TOKEN_URL"],
            api_base_url=app.config["LINKEDIN_API_BASE_URL"],
            client_kwargs={"scope": "openid profile email"},
        )

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)

    @app.cli.command("init-db")
    def init_db_command():
        db.create_all()
        print("Database initialized.")

    @app.cli.command("send-reminders")
    @click.option("--hours-ahead", default=None, type=int)
    @click.option("--dry-run", is_flag=True, default=False)
    def send_reminders_command(hours_ahead: int | None, dry_run: bool):
        """
        Envoie les rappels de rendez-vous imminents.
        Cette commande est destinee a etre executee par cron.
        """
        if hours_ahead is None:
            hours_ahead = app.config["REMINDER_HOURS_AHEAD_DEFAULT"]
        summary = send_upcoming_appointment_reminders(hours_ahead=hours_ahead, dry_run=dry_run)
        print(
            "checked={checked} sent={sent} failed={failed} skipped={skipped} dry_run={dry_run}".format(
                **summary
            )
        )

    return app
