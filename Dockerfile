# Image de base Python plus recente et legere
FROM python:3.12-slim

# Evite les .pyc et force un affichage direct des logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Definir le repertoire de travail
WORKDIR /app

# Copier les fichiers requis pour l'installation des dependances
COPY requirements.txt .

# Installer les dependances
RUN pip install --no-cache-dir -r requirements.txt

# Copier le reste des fichiers de l'application
COPY . .

# Exposer le port de l'application
EXPOSE 5000

# Demarrer Flask en ecoutant depuis l'exterieur du conteneur
CMD ["flask", "--app", "run.py", "run", "--host=0.0.0.0", "--port=5000"]
