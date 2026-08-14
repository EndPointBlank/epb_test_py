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

# The SDK comes from requirements.txt, which pins an exact tag. There used to
# be a force-reinstall from master here: requirements.txt tracked the SDK's
# default branch, and pip skips reinstalling when the version string is
# unchanged even though the git source moved underneath it.
#
# That reinstall named the repo directly with no ref, so it overrode the pin --
# this script installed master no matter what requirements.txt said, and a
# deploy could not reproduce a known-good SDK. The early-warning it provided is
# now the `sdk-canary` job in .github/workflows/ci.yml, which installs from
# master, is allowed to fail, and does not decide what this build ships.
