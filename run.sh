#!/usr/bin/env bash
# Boots backend + frontend together. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d backend/.venv ]; then
  echo "==> creating python venv"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi
if [ ! -d frontend/node_modules ]; then
  echo "==> installing node deps"
  (cd frontend && npm install --silent)
fi

echo "==> backend  http://localhost:8000/docs"
(cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000) &
BACK=$!
echo "==> frontend http://localhost:3000"
(cd frontend && npm run dev) &
FRONT=$!
trap 'kill $BACK $FRONT 2>/dev/null || true' EXIT INT TERM
wait
