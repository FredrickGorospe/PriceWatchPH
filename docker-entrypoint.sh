#!/bin/sh
set -eu

python manage.py collectstatic --noinput
exec "$@"
