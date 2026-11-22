#!/bin/sh
# Start the Personal AI OS on http://localhost:8000
cd "$(dirname "$0")"
exec .venv/bin/uvicorn app.server:app --host 127.0.0.1 --port "${PORT:-8000}"
