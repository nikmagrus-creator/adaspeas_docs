FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# Create non-root user (match typical Linux desktop UID/GID by default)
ARG UID=1000
ARG GID=1000
RUN groupadd -g ${GID} app && useradd -l -m -u ${UID} -g ${GID} -s /bin/bash app

ARG PIP_VERSION=26.0.1
RUN python -m pip install --no-cache-dir --upgrade "pip==${PIP_VERSION}"

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY src /app/src

# Ensure runtime data dir exists (volume usually mounted here)
RUN mkdir -p /data && chown -R app:app /data /app

USER app

CMD ["python", "-m", "adaspeas.bot.main"]
