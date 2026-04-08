# SPECTRE web console — production container

FROM python:3.12-slim

WORKDIR /app

# Install build dependencies (needed for some passlib/cryptography wheels)
RUN apt-get update && apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY spectre/ ./spectre/

# Install package in non-editable mode; skip pywin32 (Windows-only COM lib)
RUN pip install --no-cache-dir ".[standard]" || \
    pip install --no-cache-dir \
        fastapi uvicorn[standard] jinja2 python-multipart \
        sqlalchemy[asyncio] aiosqlite "passlib[bcrypt]" itsdangerous structlog

# Database volume mount point
VOLUME ["/app/data"]

ENV DATABASE_URL="sqlite+aiosqlite:////app/data/spectre.db"
ENV SPECTRE_LOG_LEVEL="INFO"

EXPOSE 8000

CMD ["uvicorn", "spectre.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
