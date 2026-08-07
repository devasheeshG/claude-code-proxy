#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: curl -fsSL <PROXY_ORIGIN>/install.sh | bash -s -- <BASE_URL>" >&2
  echo "The installer prompts for the API key without echoing it." >&2
  echo "For automation, set CLAUDE_PROXY_KEY_FILE to a protected file containing the key." >&2
  exit 1
}

if [ "$#" -ne 1 ]; then
  usage
fi

BASE_URL="$1"
API_KEY=""

case "$BASE_URL" in
  http://*|https://*) ;;
  *) echo "Base URL must start with http:// or https://" >&2; exit 1 ;;
esac

read_proxy_key() {
  if [ -n "${CLAUDE_PROXY_KEY_FILE:-}" ]; then
    if [ ! -f "$CLAUDE_PROXY_KEY_FILE" ] || [ ! -r "$CLAUDE_PROXY_KEY_FILE" ]; then
      echo "CLAUDE_PROXY_KEY_FILE must name a readable regular file." >&2
      exit 1
    fi
    IFS= read -r API_KEY < "$CLAUDE_PROXY_KEY_FILE" || [ -n "$API_KEY" ]
  elif [ -t 2 ]; then
    printf 'Paste the Claude Code Proxy API key (input hidden): ' > /dev/tty
    if ! IFS= read -r -s API_KEY < /dev/tty; then
      printf '\nUnable to read the API key from the terminal.\n' > /dev/tty
      exit 1
    fi
    printf '\n' > /dev/tty
  else
    echo "No interactive terminal is available." >&2
    echo "Set CLAUDE_PROXY_KEY_FILE to a protected file containing the key." >&2
    exit 1
  fi
  if [ -z "$API_KEY" ]; then
    echo "API key cannot be empty." >&2
    exit 1
  fi
}

read_proxy_key

SETTINGS="$HOME/.claude/settings.json"
mkdir -p "$HOME/.claude"

umask 077
KEY_FILE="$(mktemp "$HOME/.claude/proxy-key.XXXXXX")"
TEMP_SETTINGS=""
cleanup() {
  [ -z "${KEY_FILE:-}" ] || rm -f -- "$KEY_FILE"
  [ -z "${TEMP_SETTINGS:-}" ] || rm -f -- "$TEMP_SETTINGS"
}
trap cleanup EXIT
printf '%s\n' "$API_KEY" > "$KEY_FILE"
unset API_KEY

if command -v python3 >/dev/null 2>&1; then
  CC_INSTALL_BASE_URL="$BASE_URL" \
  CC_INSTALL_KEY_FILE="$KEY_FILE" \
  CC_INSTALL_SETTINGS="$SETTINGS" \
    python3 - <<'PY'
import json
import os
import shutil
import tempfile

path = os.environ["CC_INSTALL_SETTINGS"]
with open(os.environ["CC_INSTALL_KEY_FILE"], encoding="utf-8") as handle:
    api_key = handle.readline().rstrip("\r\n")
if not api_key:
    raise SystemExit("API key cannot be empty")
if os.path.exists(path):
    try:
        with open(path, encoding="utf-8") as handle:
            settings = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not parse {path}; it was left unchanged: {exc}")
    if not isinstance(settings, dict):
        raise SystemExit(f"Could not update {path}: its top-level value is not an object")
    shutil.copy2(path, path + ".bak")
else:
    settings = {}

env = settings.get("env")
if env is None:
    env = {}
    settings["env"] = env
elif not isinstance(env, dict):
    raise SystemExit(f"Could not update {path}: env is not an object")

env["ANTHROPIC_BASE_URL"] = os.environ["CC_INSTALL_BASE_URL"]
env["ANTHROPIC_AUTH_TOKEN"] = api_key

fd, temporary = tempfile.mkstemp(prefix="settings.json.tmp.", dir=os.path.dirname(path))
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
PY
elif command -v jq >/dev/null 2>&1; then
  if [ -f "$SETTINGS" ]; then
    jq empty "$SETTINGS" || { echo "Could not parse $SETTINGS; it was left unchanged."; exit 1; }
    cp -p "$SETTINGS" "$SETTINGS.bak"
  else
    printf '{}\n' > "$SETTINGS"
  fi
  TEMP_SETTINGS="$(mktemp "$HOME/.claude/settings.json.tmp.XXXXXX")"
  jq --rawfile key "$KEY_FILE" --arg base "$BASE_URL" \
    '.env = ((.env // {}) + {ANTHROPIC_BASE_URL: $base, ANTHROPIC_AUTH_TOKEN: ($key | rtrimstr("\\n"))})' \
    "$SETTINGS" > "$TEMP_SETTINGS"
  mv "$TEMP_SETTINGS" "$SETTINGS"
  TEMP_SETTINGS=""
  chmod 600 "$SETTINGS"
else
  echo "python3 or jq is required to safely update $SETTINGS."
  exit 1
fi

cleanup
trap - EXIT

echo
echo "Claude Code configured to use Claude Code Proxy."
echo "  Settings: $SETTINGS"
echo "  Base URL: $BASE_URL"
echo
echo "Run: claude"
