#!/usr/bin/env bash
set -e

# ensure pip is up-to-date
python -m pip install --upgrade pip

# install dependencies
pip install -r requirements.txt

# collect static files
python manage.py collectstatic --noinput

# (optional) migrate automatically
python manage.py migrate --noinput
