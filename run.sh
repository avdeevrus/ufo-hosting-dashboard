#!/usr/bin/env bash
# Запуск дашборда UFO Hosting.
# Первый запуск ставит зависимости в локальный venv, дальше — просто стартует Streamlit.

set -euo pipefail
cd "$(dirname "$0")"

VENV=".venv"

if [ ! -d "$VENV" ]; then
  echo "Создаю виртуальное окружение в $VENV…"
  python3 -m venv "$VENV"
  source "$VENV/bin/activate"
  echo "Устанавливаю зависимости…"
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
else
  source "$VENV/bin/activate"
fi

PORT="${PORT:-8520}"
echo ""
echo "🛰  UFO Hosting Dashboard"
echo "    http://localhost:$PORT"
echo ""
exec streamlit run src/app.py \
  --server.port "$PORT" \
  --browser.gatherUsageStats false
