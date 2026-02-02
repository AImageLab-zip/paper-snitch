#!/usr/bin/env sh

set -e

uv run manage.py migrate
uv run manage.py collectstatic --noinput
uv run manage.py loaddata webApp/fixtures/*.json
uv run manage.py loaddata annotator/fixtures/*.json

gunicorn web.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 3 \
  --timeout 120 \
  --access-logfile -