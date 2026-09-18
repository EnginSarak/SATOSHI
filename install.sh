#!/usr/bin/env bash
set -euo pipefail

REPO="${BTC_REPO:-EnginSarak/SATOSHI}"
BRANCH="${BTC_BRANCH:-main}"
HOME_DIR="${BTC_HOME:-$HOME/.bitcoin-core-cli}"
RAW="https://raw.githubusercontent.com/$REPO/$BRANCH"

GREEN=$'\033[38;5;82m'
ORANGE=$'\033[38;5;208m'
GREY=$'\033[38;5;245m'
RED=$'\033[38;5;196m'
RESET=$'\033[0m'

say()  { printf '%s\n' "  $*"; }
ok()   { printf '%s\n' "  ${GREEN}ok${RESET}  $*"; }
warn() { printf '%s\n' "  ${ORANGE}!${RESET}   $*"; }
die()  { printf '%s\n' "  ${RED}✕${RESET}   $*" >&2; exit 1; }

printf '\n%s\n' "${ORANGE}  bitcoin-core-cli${RESET}"
printf '%s\n\n' "${GREY}  installing to $HOME_DIR${RESET}"

command -v python3 >/dev/null 2>&1 || die "python3 not found"
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,8) else 1)' \
  || die "python 3.8+ required (found $PYV)"
ok "python $PYV"

mkdir -p "$HOME_DIR"

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SRC_DIR/btc.py" ]; then
  cp "$SRC_DIR/btc.py" "$HOME_DIR/btc.py"
  ok "copied btc.py from checkout"
else
  command -v curl >/dev/null 2>&1 || die "curl not found"
  curl -fsSL "$RAW/btc.py" -o "$HOME_DIR/btc.py" || die "download failed"
  ok "downloaded btc.py"
fi
chmod +x "$HOME_DIR/btc.py"

# --- shell alias -------------------------------------------------------------
RC="$HOME/.bashrc"
[ -n "${ZSH_VERSION:-}" ] && RC="$HOME/.zshrc"
[ -f "$RC" ] || touch "$RC"

if grep -q "bitcoin-core-cli alias" "$RC" 2>/dev/null; then
  ok "alias already present in $(basename "$RC")"
else
  {
    echo ""
    echo "# bitcoin-core-cli alias"
    echo "alias btc='python3 $HOME_DIR/btc.py'"
    echo "alias bitcoin='python3 $HOME_DIR/btc.py shell'"
  } >> "$RC"
  ok "added 'btc' and 'bitcoin' to $(basename "$RC")"
fi

# --- optional: tuya support --------------------------------------------------
if python3 -c 'import tinytuya' >/dev/null 2>&1; then
  ok "tinytuya present (tuya smart plugs supported)"
else
  say ""
  warn "tinytuya not installed — only needed for tuya smart plugs"
  say "${GREY}install later with:${RESET}"
  say "${GREY}  python3 -m pip install tinytuya --break-system-packages${RESET}"
fi

# --- done --------------------------------------------------------------------
cat <<EOF

  ${GREEN}installed${RESET}

  ${GREY}two steps left:${RESET}

    1.  source $RC
    2.  btc setup

  ${GREY}'btc setup' walks you through connecting your node, and then
  optionally electrs, wallets, your miner and a smart plug.
  You can stop after any step and re-run it later.${RESET}

  ${GREY}after that:${RESET}
    btc              ${GREY}# dashboard${RESET}
    bitcoin          ${GREY}# interactive mode${RESET}
    btc index        ${GREY}# every command${RESET}

EOF
