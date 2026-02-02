#!/usr/bin/env sh

# uv run --host 0.0.0.0 app
set -e

uv run python manage.py migrate
uv run manage.py loaddata webApp/fixtures/*.json
uv run manage.py loaddata annotator/fixtures/*.json
uv run python manage.py runserver 0.0.0.0:8000