#!/usr/bin/env bash
set -o errexit

cd "$(dirname "$0")"

python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt
