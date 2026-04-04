#!/usr/bin/env bash
# myagent Docker launcher
# Usage:
#   ./run.sh                          # interactive REPL
#   ./run.sh "fibonacci scripti yaz"  # one-shot task
#   ./run.sh --build                  # rebuild image then start REPL
#   ./run.sh --build "görev"          # rebuild then run task
#   ./run.sh --shell                  # bash shell inside container (debug)
#   ./run.sh --build --shell          # rebuild then open shell

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p workspace

# Parse flags before dispatch
BUILD=0
SHELL_MODE=0
ARGS=()

for arg in "$@"; do
    case "$arg" in
        --build) BUILD=1 ;;
        --shell) SHELL_MODE=1 ;;
        --help|-h)
            echo "Kullanım:"
            echo "  ./run.sh                          REPL modu"
            echo "  ./run.sh \"görev açıklaması\"       Tek görev çalıştır"
            echo "  ./run.sh --build                  Image'ı yeniden oluştur"
            echo "  ./run.sh --build \"görev\"          Rebuild + tek görev"
            echo "  ./run.sh --shell                  Container içine bash aç"
            echo "  ./run.sh --build --shell          Rebuild + bash"
            exit 0 ;;
        *) ARGS+=("$arg") ;;
    esac
done

if [[ $BUILD -eq 1 ]]; then
    echo "Image yeniden oluşturuluyor..."
    docker compose build
fi

if [[ $SHELL_MODE -eq 1 ]]; then
    exec docker compose run --rm --entrypoint bash myagent
elif [[ ${#ARGS[@]} -gt 0 ]]; then
    exec docker compose run --rm myagent "${ARGS[@]}"
else
    exec docker compose run --rm myagent
fi
