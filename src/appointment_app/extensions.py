from authlib.integrations.flask_client import OAuth
from flask_login import LoginManager
from flask_mail import Mail
from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Connecte-toi pour acceder a cette page."
oauth = OAuth()
mail = Mail()
