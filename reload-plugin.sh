#!/bin/bash
set -e

DIR="$(dirname "$0")"

# Pick the target platform from the first argument.
case "${1:-}" in
  openai|codex|chatgpt)
    TARGET=openai ;;
  claude|claude-desktop)
    TARGET=claude ;;
  *)
    echo "usage: $0 {openai|claude}" >&2
    exit 1 ;;
esac

# Use a local venv for the build deps (Jinja2/PyYAML). Homebrew's system python
# is externally managed (PEP 668) and can't hold them, so bootstrap one here.
VENV="$DIR/.build-venv"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/python" -m pip install -q -r "$DIR/build/requirements.txt"
fi

# Build the distribution from src/ + platforms/$TARGET/ into dist/$TARGET/,
# plus an uploadable dist/$TARGET-tableau.zip.
"$VENV/bin/python" "$DIR/build/build.py" --zip "$TARGET"
DIST="$DIR/dist/$TARGET"

# Reinstall the freshly built plugin into the chosen host.
if [ "$TARGET" = "openai" ]; then
  # Codex CLI and the ChatGPT/Codex desktop apps share ~/.codex.
  codex plugin remove Tableau@tableau-plugin || true
  codex plugin marketplace remove tableau-plugin || true
  codex plugin marketplace add "$DIST"
  codex plugin add Tableau@tableau-plugin
  echo "Built and installed. Restart the ChatGPT/Codex desktop app to load the changes."
  exit 0
fi

# Claude apps (web, Desktop, Cowork). Plugins live on the claude.ai account and
# there is no CLI or API to install them (`claude plugin install` only reaches
# Claude Code on this machine). The apps take a plugin two ways, both under
# Customize > Plugins:
#   - Add marketplace: a GitHub repo, re-read via "Check for updates" or
#     "Sync automatically".
#   - Upload plugin: a .zip with .claude-plugin/plugin.json at its root.
# If CLAUDE_MARKETPLACE_REPO names a git remote, publish the build there for the
# first route; otherwise hand over the zip for the second.
ZIP="$DIR/dist/$TARGET-tableau.zip"

open_claude() {
  if [ "$(uname)" = "Darwin" ] && open -Ra Claude 2>/dev/null; then
    open -a Claude
  fi
}

if [ -n "${CLAUDE_MARKETPLACE_REPO:-}" ]; then
  # Mirror dist/claude into a local clone of the marketplace repo and push its
  # default branch, which is the branch the apps read.
  CLONE="$DIR/.claude-marketplace"
  if [ ! -d "$CLONE/.git" ]; then
    git clone -q "$CLAUDE_MARKETPLACE_REPO" "$CLONE"
  fi
  git -C "$CLONE" pull -q --ff-only || true
  rsync -a --delete --exclude .git "$DIST/" "$CLONE/"
  git -C "$CLONE" add -A
  if git -C "$CLONE" diff --cached --quiet; then
    echo "Marketplace repo already up to date."
  else
    git -C "$CLONE" commit -q -m "Build tableau plugin from $(git -C "$DIR" rev-parse --short HEAD)"
    git -C "$CLONE" push -q origin HEAD
    echo "Pushed the build to $CLAUDE_MARKETPLACE_REPO."
  fi
  echo "In the Claude app: Customize > Plugins."
  echo "  First time: Add marketplace > $CLAUDE_MARKETPLACE_REPO, then install Tableau."
  echo "  After that: Check for updates on the marketplace (or turn on Sync automatically)."
  open_claude
else
  if [ "$(uname)" = "Darwin" ]; then
    open -R "$ZIP"
  fi
  echo "Built $ZIP."
  echo "In the Claude app: Customize > Plugins > Add > Upload plugin, and pick the zip."
  echo "  If the old version stays installed, Remove it there and upload again."
  echo "  Set CLAUDE_MARKETPLACE_REPO=<git remote> to publish to a GitHub marketplace instead."
  open_claude
fi
