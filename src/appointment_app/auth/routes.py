import re
import unicodedata

from authlib.integrations.base_client.errors import OAuthError
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user

from ..extensions import db, oauth
from ..models import CompanyProfile, OAuthAccount, User


auth_bp = Blueprint("auth", __name__, url_prefix="/auth")
PENDING_LINK_SESSION_KEY = "pending_oauth_link"


def _slugify(value: str) -> str:
    """Transforme un texte en slug URL-safe (ASCII + tirets)."""
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text.lower()).strip("-")
    return cleaned or "entreprise"


def _build_unique_company_slug(company_name: str) -> str:
    """Genere un slug unique en base a partir du nom d'entreprise."""
    base_slug = _slugify(company_name)
    candidate = base_slug
    sequence = 2

    while CompanyProfile.query.filter_by(public_slug=candidate).first() is not None:
        candidate = f"{base_slug}-{sequence}"
        sequence += 1

    return candidate


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "client").strip().lower()

        if role not in {"client", "company"}:
            role = "client"

        if not full_name or not email or not password:
            flash("Tous les champs sont obligatoires.", "error")
            return render_template("auth/register.html")

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("Cet email est deja utilise.", "error")
            return render_template("auth/register.html")

        user = User(full_name=full_name, email=email, role=role)
        user.set_password(password)

        db.session.add(user)

        # Si c'est une entreprise, on prepare sa page publique partageable.
        if role == "company":
            public_slug = _build_unique_company_slug(full_name)
            company_profile = CompanyProfile(
                user=user,
                company_name=full_name,
                public_slug=public_slug,
                booking_page_title=f"Prendre rendez-vous avec {full_name}",
            )
            db.session.add(company_profile)

        db.session.commit()

        flash("Compte cree. Tu peux maintenant te connecter.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if not user or not user.check_password(password):
            flash("Identifiants invalides.", "error")
            return render_template("auth/login.html")

        login_user(user)
        flash("Connexion reussie.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html")


def _get_oauth_client(provider: str):
    """Retourne le client OAuth configure, sinon None."""
    return oauth.create_client(provider)


def _start_oauth(provider: str, callback_endpoint: str):
    """Demarre la redirection vers le fournisseur OAuth."""
    client = _get_oauth_client(provider)
    if client is None:
        flash(
            f"Connexion {provider.capitalize()} indisponible. Verifie la configuration OAuth.",
            "error",
        )
        return redirect(url_for("auth.login"))

    redirect_uri = url_for(callback_endpoint, _external=True)
    return client.authorize_redirect(redirect_uri)


def _save_pending_link(provider: str, provider_user_id: str, email: str, full_name: str):
    """Stocke temporairement l'intention de liaison avant confirmation manuelle."""
    session[PENDING_LINK_SESSION_KEY] = {
        "provider": provider,
        "provider_user_id": str(provider_user_id).strip(),
        "email": str(email).strip().lower(),
        "full_name": str(full_name).strip(),
    }


def _create_oauth_link(user: User, provider: str, provider_user_id: str):
    """Cree la liaison fournisseur -> utilisateur et journalise l'operation."""
    oauth_account = OAuthAccount(
        provider=provider,
        provider_user_id=str(provider_user_id).strip(),
        user_id=user.id,
    )
    db.session.add(oauth_account)
    db.session.commit()

    current_app.logger.info(
        "OAuth link created: provider=%s user_id=%s email=%s",
        provider,
        user.id,
        user.email,
    )


def _link_or_login_oauth(provider: str, provider_user_id: str, email: str, full_name: str):
    """Lie un compte OAuth a un utilisateur local, avec confirmation si email existant."""
    provider_user_id = str(provider_user_id).strip()
    email = str(email).strip().lower()
    full_name = str(full_name).strip()

    if not provider_user_id or not email:
        flash(f"Impossible de recuperer le profil {provider.capitalize()}.", "error")
        return redirect(url_for("auth.login"))

    linked_account = OAuthAccount.query.filter_by(
        provider=provider, provider_user_id=provider_user_id
    ).first()
    if linked_account:
        login_user(linked_account.user)
        flash(f"Connexion {provider.capitalize()} reussie.", "success")
        return redirect(url_for("main.dashboard"))

    user = User.query.filter_by(email=email).first()
    if user is None:
        # Nouveau compte: creation + liaison immediate.
        display_name = full_name or email.split("@")[0]
        user = User(full_name=display_name, email=email, role="client")
        db.session.add(user)
        db.session.flush()

        _create_oauth_link(user=user, provider=provider, provider_user_id=provider_user_id)
        login_user(user)
        flash(f"Compte {provider.capitalize()} cree et connexion reussie.", "success")
        return redirect(url_for("main.dashboard"))

    if current_user.is_authenticated and current_user.id == user.id:
        # Cas "je suis deja connecte et je lie un nouveau fournisseur".
        _create_oauth_link(user=user, provider=provider, provider_user_id=provider_user_id)
        flash(f"Compte {provider.capitalize()} lie a ton profil.", "success")
        return redirect(url_for("main.dashboard"))

    # Securite: email deja present => confirmation explicite obligatoire.
    _save_pending_link(
        provider=provider,
        provider_user_id=provider_user_id,
        email=email,
        full_name=full_name,
    )
    flash(
        "Un compte existe deja avec cet email. Confirme avec ton mot de passe pour lier ce fournisseur.",
        "warning",
    )
    return redirect(url_for("auth.confirm_link"))


def _fetch_google_identity(client):
    """Google expose les infos via OpenID Connect userinfo."""
    userinfo_response = client.get("https://openidconnect.googleapis.com/v1/userinfo")
    userinfo = userinfo_response.json()
    return {
        "provider_user_id": userinfo.get("sub", ""),
        "email": userinfo.get("email", ""),
        "full_name": userinfo.get("name", ""),
    }


def _fetch_github_identity(client):
    """GitHub peut ne pas retourner l'email dans /user, on lit /user/emails en fallback."""
    profile_response = client.get("user")
    profile = profile_response.json()

    provider_user_id = profile.get("id", "")
    email = str(profile.get("email", "")).strip().lower()
    full_name = str(profile.get("name", "")).strip() or str(profile.get("login", "")).strip()

    if not email:
        emails_response = client.get("user/emails")
        if emails_response.status_code < 400:
            emails = emails_response.json()
            for entry in emails:
                entry_email = str(entry.get("email", "")).strip().lower()
                is_verified = bool(entry.get("verified"))
                is_primary = bool(entry.get("primary"))
                if entry_email and is_primary and is_verified:
                    email = entry_email
                    break
            if not email:
                for entry in emails:
                    entry_email = str(entry.get("email", "")).strip().lower()
                    if entry_email:
                        email = entry_email
                        break

    return {
        "provider_user_id": provider_user_id,
        "email": email,
        "full_name": full_name,
    }


def _fetch_facebook_identity(client):
    """Facebook userinfo via Graph API."""
    userinfo_response = client.get("me", params={"fields": "id,name,email"})
    userinfo = userinfo_response.json()
    return {
        "provider_user_id": userinfo.get("id", ""),
        "email": userinfo.get("email", ""),
        "full_name": userinfo.get("name", ""),
    }


def _fetch_linkedin_identity(client):
    """LinkedIn OIDC userinfo (openid profile email)."""
    userinfo_response = client.get("userinfo")
    userinfo = userinfo_response.json()
    return {
        "provider_user_id": userinfo.get("sub", ""),
        "email": userinfo.get("email", ""),
        "full_name": userinfo.get("name", ""),
    }


def _oauth_callback(provider: str, identity_fetcher):
    """Finalise le flux OAuth d'un fournisseur (token + profil + liaison locale)."""
    client = _get_oauth_client(provider)
    if client is None:
        flash(f"Connexion {provider.capitalize()} indisponible.", "error")
        return redirect(url_for("auth.login"))

    try:
        client.authorize_access_token()
        identity = identity_fetcher(client)
    except OAuthError:
        flash(f"Echec de la connexion {provider.capitalize()}. Reessaie.", "error")
        return redirect(url_for("auth.login"))
    except Exception:
        current_app.logger.exception("OAuth callback failed: provider=%s", provider)
        flash(f"Erreur technique pendant la connexion {provider.capitalize()}.", "error")
        return redirect(url_for("auth.login"))

    return _link_or_login_oauth(
        provider=provider,
        provider_user_id=identity.get("provider_user_id", ""),
        email=identity.get("email", ""),
        full_name=identity.get("full_name", ""),
    )


@auth_bp.route("/confirm-link", methods=["GET", "POST"])
def confirm_link():
    """Demande le mot de passe local avant de lier un compte social sur email existant."""
    pending = session.get(PENDING_LINK_SESSION_KEY)
    if not pending:
        flash("Aucune liaison en attente.", "warning")
        return redirect(url_for("auth.login"))

    provider = str(pending.get("provider", "")).strip()
    provider_user_id = str(pending.get("provider_user_id", "")).strip()
    email = str(pending.get("email", "")).strip().lower()

    if request.method == "POST":
        password = request.form.get("password", "")
        user = User.query.filter_by(email=email).first()

        if user is None:
            session.pop(PENDING_LINK_SESSION_KEY, None)
            flash("Le compte local n'existe plus. Recommence la connexion sociale.", "error")
            return redirect(url_for("auth.login"))

        # Mesure de securite: confirmation par mot de passe local.
        if not user.password_hash or not user.check_password(password):
            flash("Mot de passe invalide. Liaison annulee.", "error")
            return render_template("auth/confirm_link.html", provider=provider, email=email)

        existing_link = OAuthAccount.query.filter_by(
            provider=provider, provider_user_id=provider_user_id
        ).first()
        if existing_link:
            session.pop(PENDING_LINK_SESSION_KEY, None)
            login_user(existing_link.user)
            flash(f"Connexion {provider.capitalize()} reussie.", "success")
            return redirect(url_for("main.dashboard"))

        _create_oauth_link(user=user, provider=provider, provider_user_id=provider_user_id)
        session.pop(PENDING_LINK_SESSION_KEY, None)
        login_user(user)
        flash(f"Compte {provider.capitalize()} lie apres confirmation.", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("auth/confirm_link.html", provider=provider, email=email)


@auth_bp.route("/cancel-link")
def cancel_link():
    """Permet d'abandonner explicitement la liaison en attente."""
    session.pop(PENDING_LINK_SESSION_KEY, None)
    flash("Liaison annulee.", "warning")
    return redirect(url_for("auth.login"))


@auth_bp.route("/google")
def google_login():
    return _start_oauth("google", "auth.google_callback")


@auth_bp.route("/google/callback")
def google_callback():
    return _oauth_callback("google", _fetch_google_identity)


@auth_bp.route("/github")
def github_login():
    return _start_oauth("github", "auth.github_callback")


@auth_bp.route("/github/callback")
def github_callback():
    return _oauth_callback("github", _fetch_github_identity)


@auth_bp.route("/facebook")
def facebook_login():
    return _start_oauth("facebook", "auth.facebook_callback")


@auth_bp.route("/facebook/callback")
def facebook_callback():
    return _oauth_callback("facebook", _fetch_facebook_identity)


@auth_bp.route("/linkedin")
def linkedin_login():
    return _start_oauth("linkedin", "auth.linkedin_callback")


@auth_bp.route("/linkedin/callback")
def linkedin_callback():
    return _oauth_callback("linkedin", _fetch_linkedin_identity)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    if current_user.is_authenticated:
        logout_user()
        flash("Tu es deconnecte.", "success")
    return redirect(url_for("main.home"))
