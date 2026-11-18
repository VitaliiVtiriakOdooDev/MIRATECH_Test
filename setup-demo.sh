#!/bin/sh
set -eu
cd "$(dirname "$0")"
delta_db="${DELTA_DB:-delta_demo}"
docker compose build odoo
docker compose up -d --wait db
docker compose run --rm --no-deps odoo odoo -d "$delta_db" -i delta_consolidation --without-demo=all --stop-after-init
docker compose run --rm --no-deps -T odoo odoo shell -d "$delta_db" < demo.py
docker compose run --rm --no-deps -T odoo odoo shell -d "$delta_db" < verify-demo.py
docker compose up -d odoo
