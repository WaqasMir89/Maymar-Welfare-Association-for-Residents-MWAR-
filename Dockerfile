FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# System deps for psycopg + Pillow + cryptography wheels; gettext for i18n.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev gettext \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt psycopg[binary]

COPY . .

RUN python manage.py compilemessages -l ur \
    && python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
