# README pour le Dockerfile - [Appointment-management-system](https://github.com/hdmanoach/Appointment-management-system)

## Description

Ce Dockerfile permet de conteneuriser l'application **[Appointment-management-system](https://github.com/hdmanoach/Appointment-management-system)**, une application web développée avec Flask pour la gestion de rendez-vous. Il utilise une image Python légère (3.12-slim) pour optimiser la taille et les performances.

## Prérequis

- Docker installé sur votre système.
- Assurez-vous que le fichier `requirements.txt` est présent dans le répertoire racine du projet, contenant toutes les dépendances Python nécessaires.

## Construction de l'image Docker

Pour construire l'image Docker, exécutez la commande suivante dans le répertoire contenant le Dockerfile :

```bash
docker build -t appointment-management-system .
```

- `-t appointment-management-system` : Nom de l'image (vous pouvez le changer si souhaité).

## Exécution du conteneur

Une fois l'image construite, lancez le conteneur avec la commande suivante :

```bash
docker run --name appointment-app --env-file .env -p 5000:5000 appointment-management-system
```

- `-p 5000:5000` : Mappe le port 5000 du conteneur au port 5000 de votre machine hôte.
- `--env-file .env` : Injecte les variables de configuration (SECRET_KEY, OAuth, SMTP, etc.) sans les copier dans l'image.
- L'application sera accessible via `http://localhost:5000`.

## Variables d'environnement

Le Dockerfile définit les variables suivantes pour optimiser l'exécution :

- `PYTHONDONTWRITEBYTECODE=1` : Évite la génération de fichiers .pyc.
- `PYTHONUNBUFFERED=1` : Force l'affichage direct des logs sans buffer.

## Structure du projet

Assurez-vous que la structure de votre projet ressemble à ceci :

```
Appointment-management-system/
├── dockerfile
├── requirements.txt
├── run.py
└── src/
    └── appointment_app/
        └── ... (autres fichiers de l'application)
```

## Commande de démarrage

L'application démarre avec la commande Flask :

```bash
flask --app run.py run --host=0.0.0.0 --port=5000
```

Cela permet à Flask d'écouter sur toutes les interfaces réseau du conteneur.

## Dépannage

- Si le port 5000 est déjà utilisé, changez le mapping des ports : `docker run -p 8080:5000 appointment-management-system` (accessible via `http://localhost:8080`).
- Vérifiez les logs du conteneur avec `docker logs -f appointment-app` en cas d'erreur.
- Pour voir les logs fichier dans le conteneur :

```bash
docker exec -it appointment-app sh -c "tail -f /app/instance/logs/app.log"
```

## Sécurité appliquée dans le code

- Cookies de session durcis (`HttpOnly`, `SameSite`, option `Secure` via `.env`).
- Protection CSRF pour toutes les routes en écriture (POST/PUT/PATCH/DELETE).
- En-têtes HTTP de sécurité ajoutés (CSP, `X-Frame-Options`, `X-Content-Type-Options`, etc.).
- Logging applicatif rotatif (fichier + sortie console) avec niveau configurable.

Variables utiles à régler dans `.env` :

```env
SESSION_COOKIE_SECURE=true
REMEMBER_COOKIE_SECURE=true
LOG_LEVEL=INFO
LOG_FILE=instance/logs/app.log
```

## Notes

- Ce Dockerfile est optimisé pour un environnement de production léger.
- Pour le développement, vous pouvez monter un volume pour les changements en temps réel : `docker run -p 5000:5000 -v $(pwd):/app appointment-management-system`.
