#!/usr/bin/env bash
set -o errexit

cd "$(dirname "$0")"

# Local dev only: create the database if it doesn't exist. Tables are created
# on app startup by `db.setup()` (CREATE TABLE IF NOT EXISTS).
if [ -z "$DATABASE_URL" ]; then
    PGPASSWORD="${PGPASSWORD:-postgres}" createdb \
        -h "${PGHOST:-localhost}" \
        -U "${PGUSER:-postgres}" \
        epb_test_py_development 2>/dev/null || true
fi

python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt

# pip skips reinstalling end-point-blank-py when the package version is
# unchanged, even after the git source moves. Force a fresh clone from master.
.venv/bin/pip install --upgrade --force-reinstall --no-deps \
    git+https://github.com/EndPointBlank/end_point_blank_py.git
