# source this: sets the server, key and CA bundle for the kit
set -a; . "$(dirname "${BASH_SOURCE[0]:-$0}")/.env"; set +a
export SPREAD_URL=https://spread.bahnexpress.com
export SSL_CERT_FILE="$(/Users/umarbek/Documents/claude/hackjunction2026/.venv/bin/python -c 'import certifi;print(certifi.where())')"
