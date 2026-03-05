# Appointment Management System

Application Flask de gestion de rendez-vous avec architecture evolutive:
- Flask app factory
- Blueprints (`auth`, `main`)
- SQLAlchemy
- Auth locale (inscription, connexion, deconnexion)
- OAuth Google/GitHub/Facebook/LinkedIn (via Authlib)
- Compte entreprise avec lien public personnel (`/c/<slug>`)
- Module rendez-vous (creation client + suivi statut entreprise)
- Gestion des disponibilites hebdomadaires (jour + plage horaire)
- Calendrier FullCalendar (vue semaine des creneaux disponibles/occupes)
- Rappels email automatisables via cron
- Journal des envois de rappels + email HTML

## Structure

```text
Appointment-management-system/
├── run.py
├── requirements.txt
├── .env.example
└── src/
    └── appointment_app/
        ├── __init__.py
        ├── config.py
        ├── extensions.py
        ├── models.py
        ├── auth/
        │   ├── __init__.py
        │   └── routes.py
        ├── main/
        │   ├── __init__.py
        │   └── routes.py
        ├── static/
        │   └── css/style.css
        └── templates/
            ├── base.html
            ├── auth/
            └── main/
```

## Installation

1. Creer et activer un environnement virtuel

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Installer les dependances

```bash
pip install -r requirements.txt
```

3. Exporter les variables d'environnement

```bash
cp .env.example .env
export $(grep -v '^#' .env | xargs)
export PYTHONPATH=src
```

4. Initialiser la base

```bash
flask init-db
```

Si `instance/app.db` existe deja avec un ancien schema, supprime-le puis relance `flask init-db`.

5. Lancer l'application

```bash
flask run
```

## Configuration OAuth (Google, GitHub, Facebook, LinkedIn)

1. Creer les identifiants OAuth dans chaque console fournisseur (type Web Application/app web).
2. Ajouter les URLs de redirection autorisees:

```text
http://127.0.0.1:5000/auth/google/callback
http://127.0.0.1:5000/auth/github/callback
http://127.0.0.1:5000/auth/facebook/callback
http://127.0.0.1:5000/auth/linkedin/callback
```

3. Renseigner les variables dans `.env`:

```env
GOOGLE_CLIENT_ID=ton-client-id
GOOGLE_CLIENT_SECRET=ton-client-secret
GOOGLE_SERVER_METADATA_URL=https://accounts.google.com/.well-known/openid-configuration
GITHUB_CLIENT_ID=ton-client-id
GITHUB_CLIENT_SECRET=ton-client-secret
GITHUB_AUTHORIZE_URL=https://github.com/login/oauth/authorize
GITHUB_ACCESS_TOKEN_URL=https://github.com/login/oauth/access_token
GITHUB_API_BASE_URL=https://api.github.com/
FACEBOOK_CLIENT_ID=ton-client-id
FACEBOOK_CLIENT_SECRET=ton-client-secret
FACEBOOK_AUTHORIZE_URL=https://www.facebook.com/v20.0/dialog/oauth
FACEBOOK_ACCESS_TOKEN_URL=https://graph.facebook.com/v20.0/oauth/access_token
FACEBOOK_API_BASE_URL=https://graph.facebook.com/v20.0/
LINKEDIN_CLIENT_ID=ton-client-id
LINKEDIN_CLIENT_SECRET=ton-client-secret
LINKEDIN_AUTHORIZE_URL=https://www.linkedin.com/oauth/v2/authorization
LINKEDIN_ACCESS_TOKEN_URL=https://www.linkedin.com/oauth/v2/accessToken
LINKEDIN_API_BASE_URL=https://api.linkedin.com/v2/
```

## Routes initiales

- `/` : accueil
- `/auth/register` : inscription
- `/auth/login` : connexion
- `/auth/google` : redirection vers Google
- `/auth/google/callback` : retour OAuth Google
- `/auth/github` : redirection vers GitHub
- `/auth/github/callback` : retour OAuth GitHub
- `/auth/facebook` : redirection vers Facebook
- `/auth/facebook/callback` : retour OAuth Facebook
- `/auth/linkedin` : redirection vers LinkedIn
- `/auth/linkedin/callback` : retour OAuth LinkedIn
- `/auth/confirm-link` : confirmation de liaison (mot de passe local)
- `/auth/cancel-link` : annulation de liaison en attente
- `/auth/logout` : deconnexion
- `/dashboard` : zone connectee
- `/companies` : catalogue des entreprises actives (choix client)
- `/c/<slug-entreprise>` : page publique de prise de rendez-vous d'une entreprise
- `/c/<slug-entreprise>/calendar-events` : flux JSON FullCalendar des creneaux
- `/company/appointments/<id>/status` : mise a jour statut d'un rendez-vous par l'entreprise
- `/company/appointments/<id>/send-mail` : envoi manuel du mail client (si non envoye)
- `/company/availabilities` : ajout d'une disponibilite entreprise
- `/company/availabilities/<id>/delete` : suppression d'une disponibilite entreprise
- `/my-appointments` : espace client (liste des rendez-vous)
- `/my-appointments/<id>/cancel` : annulation client
- `/my-appointments/<id>/reschedule` : report client
- `flask send-reminders` : envoi des rappels (commande CLI cron)
- `/stream/company-appointments` : flux SSE temps reel du dashboard entreprise
- `/stream/my-appointments` : flux SSE temps reel de l'espace client

## Comportement entreprise

- Lorsqu'un utilisateur s'inscrit avec le role `company`, l'application cree un profil entreprise.
- Un slug unique est genere automatiquement (ex: `clinique-saint-paul`).
- L'entreprise retrouve son lien public dans le dashboard et peut le partager aux clients.
- Le dashboard entreprise traite les rendez-vous `reported` et decide du statut final.
- Le dashboard entreprise permet d'ajouter/supprimer des disponibilites hebdomadaires.
- Le dashboard entreprise affiche les rendez-vous par blocs de statut (`pending`, `reported`, `confirmed`, `paid`, `cancelled`).
- Chaque carte affiche l'heure d'envoi du mail de rappel (`reminder_sent_at`) et un bouton d'envoi manuel si le mail n'a pas encore ete envoye.
- Un rendez-vous en `paid` est verrouille (changement de statut interdit).

## Politique Multi-Entreprises

- Chaque entreprise a un compte separe et un espace admin isole.
- Le client choisit d'abord l'entreprise via `/companies`, puis reserve sur la page dediee de cette entreprise.
- La route `/companies` est reservee aux profils client.
- Chaque rendez-vous est lie a une seule entreprise (`appointment.company_id`), ce qui isole les calendriers.
- Une entreprise ne peut modifier que ses propres rendez-vous/disponibilites (filtres par `company_id` + controle d'acces).
- Les clients peuvent avoir des rendez-vous avec plusieurs entreprises sans melange des donnees.
- Les rappels email utilisent les infos de l'entreprise associee au rendez-vous.

## Comportement client (page publique entreprise)

- Le client reserve avec nom, email, date/heure et note optionnelle.
- Le rendez-vous est cree au statut `pending`.
- Un controle simple evite la reservation d'un meme creneau deja pris (a la meme heure).
- Une reservation est acceptee uniquement si la date/heure tombe dans les disponibilites configurees.

## Espace client connecte

- Le client connecte peut consulter ses rendez-vous dans `Mes rendez-vous`.
- Il peut annuler un rendez-vous.
- Il peut reporter depuis tout bloc sauf `paid` (le statut passe a `reported`).
- Un rendez-vous en `paid` est bloque cote client (annulation/report interdits).
- La vue client est organisee par blocs de statut avec rafraichissement automatique.
- Un flux SSE met a jour l'interface automatiquement quand les donnees changent (sans action manuelle).
- Le flux SSE utilise une signature baseline pour eviter les boucles de rafraichissement.

## Rappels email (cron)

Configurer les variables SMTP dans `.env`:

```env
MAIL_ENABLED=true
MAIL_HOST=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=ton-email (email de l'entreprise)
MAIL_PASSWORD=ton-mot-de-passe-app
MAIL_FROM=ton-email (e-mail de l'entreprise)
REMINDER_HOURS_AHEAD_DEFAULT=24
UI_AUTO_REFRESH_SECONDS=20
```

Commande manuelle:

```bash
flask send-reminders
```

Par defaut, `flask send-reminders` utilise `REMINDER_HOURS_AHEAD_DEFAULT` (24 heures par defaut).
Tu peux surcharger ponctuellement:

```bash
flask send-reminders --hours-ahead 6
```

Mode test (sans envoi):

```bash
flask send-reminders --hours-ahead 24 --dry-run
```

La commande journalise chaque tentative (`sent`, `failed`, `skipped`) en base.
Le rappel est envoye en texte + HTML (template: `src/appointment_app/templates/emails/reminder.html`).

Mise a jour automatique client:
- La page `Mes rendez-vous` se rafraichit automatiquement selon `UI_AUTO_REFRESH_SECONDS` (20s par defaut).

## Journalisation applicative

- Niveau configurable avec `LOG_LEVEL` (ex: `INFO`, `DEBUG`, `ERROR`).
- Fichier configurable avec `LOG_FILE` (defaut: `instance/logs/app.log`).
- Rotation automatique des logs via fichier rotatif.

Exemple cron (toutes les 15 minutes):

```cron
*/15 * * * * cd /home/manoach/Documents/PYTHON/Flask/Appointment-management-system && /home/manoach/Documents/PYTHON/Flask/env/bin/flask send-reminders --hours-ahead 24 >> /tmp/appointment_reminders.log 2>&1
```
