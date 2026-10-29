
# syntax=docker/dockerfile:1

# ============================================================
# Stage 1 — Builder
# ============================================================
FROM python:3.11-slim AS builder

WORKDIR /build

# ============================================================
# Mise à jour sécurité Debian + outils de compilation
# ============================================================
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# Environnement virtuel
# ============================================================
RUN python -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ============================================================
# Contraintes de sécurité
# ============================================================
COPY constraints.txt .

# ============================================================
# Mise à jour des outils Python
# ============================================================
RUN pip install --no-cache-dir \
        --upgrade \
        -c constraints.txt \
        pip \
        setuptools \
        wheel

# ============================================================
# Dépendances applicatives
# ============================================================
COPY requirements.txt .

RUN pip install --no-cache-dir \
        -c constraints.txt \
        -r requirements.txt

# ============================================================
# Vérification des versions de sécurité
# ============================================================
RUN python -c "\
from importlib.metadata import version; \
print('msgpack:', version('msgpack')); \
print('setuptools:', version('setuptools')); \
print('pip:', version('pip'))"

# ============================================================
# Suppression du SBOM embarqué de pip
# ============================================================
RUN rm -f /opt/venv/lib/python3.11/site-packages/pip/_vendor/bom.cdx.json

# ============================================================
# Vérification suppression SBOM
# ============================================================
RUN if [ -f /opt/venv/lib/python3.11/site-packages/pip/_vendor/bom.cdx.json ]; then \
        echo "ERROR: obsolete pip SBOM still exists"; \
        exit 1; \
    else \
        echo "OK: pip SBOM removed"; \
    fi


# ============================================================
# Stage 2 — Runtime
# ============================================================
FROM python:3.11-slim AS runtime

WORKDIR /app

# ============================================================
# Mise à jour sécurité Debian
#
# Important :
# le runtime est une nouvelle image FROM python:3.11-slim.
# Les correctifs appliqués dans le builder ne sont donc pas
# hérités ici.
# ============================================================
RUN apt-get update \
    && apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# Utilisateur non-root
# ============================================================
RUN groupadd --system app \
    && useradd --system \
        --gid app \
        --no-create-home \
        app

# ============================================================
# Copier uniquement le venv applicatif
# ============================================================
COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ============================================================
# Supprimer les outils Python système inutiles
# ============================================================
RUN rm -rf \
        /usr/local/lib/python3.11/site-packages/setuptools* \
        /usr/local/lib/python3.11/site-packages/wheel* \
        /usr/local/lib/python3.11/site-packages/pip* \
        /usr/local/lib/python3.11/ensurepip

# ============================================================
# Code applicatif
# ============================================================
COPY evaluation/ ./evaluation/
COPY agent/ ./agent/

# ============================================================
# Permissions
# ============================================================
RUN chown -R app:app /app

# ============================================================
# Healthcheck
# ============================================================
HEALTHCHECK \
    --interval=30s \
    --timeout=3s \
    --start-period=10s \
    --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health').read()" || exit 1

# ============================================================
# Utilisateur non-root
# ============================================================
USER app

EXPOSE 8000

# ============================================================
# Démarrage
# ============================================================
CMD ["uvicorn", "evaluation.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

