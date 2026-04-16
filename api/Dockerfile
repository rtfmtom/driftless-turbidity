FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq5 \
        libgeos-dev \
        libproj-dev \
        libspatialindex-dev \
        libexpat1 \
        libxml2 \
        libeccodes0 \
        libeccodes-data \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
RUN pip install -e .

COPY alembic.ini ./
COPY entrypoint.sh ./
COPY tests ./tests
RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
CMD ["api"]
