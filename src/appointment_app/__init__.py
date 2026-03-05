from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler

import click
from flask import Flask

from .auth import auth_bp
from .config import Config
from .extensions import db, login_manager, mail, oauth
from .main import main_bp
from .notifications import send_upcoming_appointment_reminders


def _configure_logging(app: Flask) -> None:
    """
    Configure la journalisation applicative:
    - sortie fichier rotatif (audit)
    - sortie console (dev/debug)
    """
    log_path = Path(app.config["LOG_FILE"])
    if not log_path.is_absolute():
        log_path = Path(app.root_path).parent.parent / log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    app.logger.handlers.clear()
    app.logger.addHandler(file_handler)
    app.logger.addHandler(console_handler)
    app.logger.setLevel(getattr(logging, app.config["LOG_LEVEL"].upper(), logging.INFO))


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    oauth.init_app(app)
    mail.init_app(app)
    _configure_logging(app)

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
