#!/usr/bin/env bash
# Локальний запуск Streamlit з venv і CA-bundle (certifi).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install -q -U pip certifi
python -m pip install -q -r requirements.txt

export SSL_CERT_FILE="$(python -c 'import certifi; print(certifi.where())')"
export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"

echo "CA bundle: $SSL_CERT_FILE"
echo "Запуск Streamlit: http://localhost:8501"
exec streamlit run app.py
