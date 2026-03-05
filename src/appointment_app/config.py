import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB_PATH = BASE_DIR / "instance" / "app.db"


def _build_database_uri() -> str:
    """
    Normalise DATABASE_URL:
    - sqlite relatif -> chemin absolu base sur BASE_DIR
    - sqlite absolu / autres drivers -> conserve tel quel
    """
    raw_uri = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

    if raw_uri.startswith("sqlite:///") and not raw_uri.startswith("sqlite:////"):
        sqlite_path = raw_uri.replace("sqlite:///", "", 1)
        path_obj = Path(sqlite_path)
        if not path_obj.is_absolute():
            path_obj = BASE_DIR / path_obj
        return f"sqlite:///{path_obj}"

    return raw_uri


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key")
    SQLALCHEMY_DATABASE_URI = _build_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_SERVER_METADATA_URL = os.getenv(
        "GOOGLE_SERVER_METADATA_URL",
        "https://accounts.google.com/.well-known/openid-configuration",
    )
    GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
    GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")
    GITHUB_AUTHORIZE_URL = os.getenv(
        "GITHUB_AUTHORIZE_URL", "https://github.com/login/oauth/authorize"
    )
    GITHUB_ACCESS_TOKEN_URL = os.getenv(
        "GITHUB_ACCESS_TOKEN_URL", "https://github.com/login/oauth/access_token"
    )
    GITHUB_API_BASE_URL = os.getenv("GITHUB_API_BASE_URL", "https://api.github.com/")
    """FACEBOOK_CLIENT_ID = os.getenv("FACEBOOK_CLIENT_ID")
    FACEBOOK_CLIENT_SECRET = os.getenv("FACEBOOK_CLIENT_SECRET")
    FACEBOOK_AUTHORIZE_URL = os.getenv(
        "FACEBOOK_AUTHORIZE_URL", "https://www.facebook.com/v20.0/dialog/oauth"
    )
    FACEBOOK_ACCESS_TOKEN_URL = os.getenv(
        "FACEBOOK_ACCESS_TOKEN_URL",
        "https://graph.facebook.com/v20.0/oauth/access_token",
    )
    FACEBOOK_API_BASE_URL = os.getenv(
        "FACEBOOK_API_BASE_URL", "https://graph.facebook.com/v20.0/"
    )"""
    LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID")
    LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET")
    LINKEDIN_AUTHORIZE_URL = os.getenv(
        "LINKEDIN_AUTHORIZE_URL", "https://www.linkedin.com/oauth/v2/authorization"
    )
    LINKEDIN_ACCESS_TOKEN_URL = os.getenv(
        "LINKEDIN_ACCESS_TOKEN_URL", "https://www.linkedin.com/oauth/v2/accessToken"
    )
    LINKEDIN_API_BASE_URL = os.getenv(
        "LINKEDIN_API_BASE_URL", "https://api.linkedin.com/v2/"
    )
    
    # Configuration Flask-Mail pour l'envoi des rappels et confirmations de rendez-vous.
    MAIL_SERVER = os.getenv("MAIL_HOST", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "true").lower() in ("true", "1", "yes")
    MAIL_USERNAME = os.getenv("MAIL_USERNAME")
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
    MAIL_DEFAULT_SENDER = os.getenv("MAIL_FROM", "no-reply@example.com")
    
    # Rappels email et paramètres UI
    MAIL_ENABLED = os.getenv("MAIL_ENABLED", "false").lower() in ("true", "1", "yes")
    REMINDER_HOURS_AHEAD_DEFAULT = int(os.getenv("REMINDER_HOURS_AHEAD_DEFAULT", 24))
    UI_AUTO_REFRESH_SECONDS = int(os.getenv("UI_AUTO_REFRESH_SECONDS", 20))
    # Journalisation applicative (utilisee par _configure_logging dans __init__.py)
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    LOG_FILE = os.getenv("LOG_FILE", "instance/logs/app.log")
