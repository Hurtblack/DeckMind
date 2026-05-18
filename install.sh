#!/usr/bin/env bash
# DeckMind installer — one-shot setup for the deckmind shell function
# and (optionally) your LLM API key.
#
# Idempotent: safe to run multiple times. Skips anything already configured.
# Never touches anything outside ~/.bashrc.

set -euo pipefail

BASHRC="$HOME/.bashrc"
MARKER="# >>> deckmind setup >>>"
END_MARKER="# <<< deckmind setup <<<"

echo
echo "DeckMind installer"
echo "──────────────────"
echo

# ----------------------------------------------------------------------------
# Step 1: install uv if missing
# ----------------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
    echo "→ uv not found. Installing…"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck source=/dev/null
    source "$HOME/.local/bin/env"
    echo "  ✓ uv installed"
else
    echo "→ uv already installed ($(uv --version))"
fi

# ----------------------------------------------------------------------------
# Step 2: install dependencies
# ----------------------------------------------------------------------------
echo "→ Installing Python dependencies via uv sync…"
uv sync --quiet
echo "  ✓ Dependencies ready"

# ----------------------------------------------------------------------------
# Step 3: add shell functions to ~/.bashrc (idempotent)
# ----------------------------------------------------------------------------
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if grep -qF "$MARKER" "$BASHRC" 2>/dev/null; then
    echo "→ Shell functions already present in ~/.bashrc — skipping."
else
    echo "→ Adding 'deckmind' and 'deckmind-update' shell functions to ~/.bashrc…"
    {
        echo ""
        echo "$MARKER"
        echo "deckmind() { (cd \"$PROJECT_DIR\" && uv run python ./main.py \"\$@\"); }"
        echo "deckmind-update() { (cd \"$PROJECT_DIR\" && git pull && uv sync); }"
        echo "$END_MARKER"
    } >> "$BASHRC"
    echo "  ✓ Functions added"
fi

# ----------------------------------------------------------------------------
# Step 4: API key setup (skippable)
# ----------------------------------------------------------------------------
echo
echo "── LLM provider setup ─────────────────────────────────────"
echo "Skip with Ctrl-C if you've already configured env vars elsewhere."
echo

# Detect what's already set so we don't pester re-runs.
provider_set="${LLM_PROVIDER:-}"
key_already=""
case "$provider_set" in
    openai|openai-chat) key_already="${OPENAI_API_KEY:-}" ;;
    deepseek)            key_already="${DEEPSEEK_API_KEY:-}" ;;
    moonshot)            key_already="${MOONSHOT_API_KEY:-}" ;;
    qwen)                key_already="${DASHSCOPE_API_KEY:-}" ;;
esac

if [[ -n "$provider_set" && -n "$key_already" ]]; then
    echo "→ Detected LLM_PROVIDER=$provider_set + matching API key already set."
    echo "  Skipping — re-run after `unset LLM_PROVIDER` if you want to change."
else
    echo "Which LLM provider would you like to use?"
    echo "  1) openai     (default)"
    echo "  2) deepseek"
    echo "  3) moonshot   (Kimi)"
    echo "  4) qwen       (通义千问)"
    echo "  5) skip — I'll set env vars manually later"
    read -rp "Choice [1-5, default 1]: " choice
    choice="${choice:-1}"

    case "$choice" in
        1) provider="openai";    key_env="OPENAI_API_KEY"     ;;
        2) provider="deepseek";  key_env="DEEPSEEK_API_KEY"   ;;
        3) provider="moonshot";  key_env="MOONSHOT_API_KEY"   ;;
        4) provider="qwen";      key_env="DASHSCOPE_API_KEY"  ;;
        5) provider=""; key_env=""; echo "→ Skipping API-key setup." ;;
        *) echo "Unknown choice. Skipping API-key setup."; provider=""; key_env="" ;;
    esac

    if [[ -n "$provider" ]]; then
        # -s = silent (no echo) so the key never appears on screen
        # or in scrollback / Konsole history.
        read -rsp "Paste your $key_env (input hidden, press Enter when done): " api_key
        echo
        if [[ -z "$api_key" ]]; then
            echo "→ No key entered. Skipping."
        else
            {
                echo ""
                echo "# DeckMind LLM config (added $(date '+%Y-%m-%d'))"
                echo "export LLM_PROVIDER=$provider"
                echo "export $key_env=$api_key"
            } >> "$BASHRC"
            echo "  ✓ Wrote LLM_PROVIDER + $key_env to ~/.bashrc"
        fi
    fi
fi

# ----------------------------------------------------------------------------
# Done
# ----------------------------------------------------------------------------
echo
echo "──────────────────"
echo "Setup complete."
echo
echo "Open a NEW terminal (so ~/.bashrc reloads), then run:"
echo
echo "    deckmind"
echo
echo "Other commands:"
echo "    deckmind -v        # verbose / developer mode"
echo "    deckmind-update    # git pull + uv sync"
echo
