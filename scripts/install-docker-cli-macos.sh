#!/usr/bin/env bash
# Install Docker via CLI on macOS (no manual download from docker.com).
# Uses Homebrew + Colima (lightweight; no Docker Desktop GUI required).
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This helper is for macOS. On Linux: use your package manager (e.g. apt install docker.io)."
  exit 1
fi

if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  echo "Docker already works: $(docker --version)"
  exit 0
fi

if ! command -v brew >/dev/null; then
  echo "Homebrew not found. Install it (one-time, in Terminal):"
  echo ""
  echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
  echo ""
  echo "Then follow the PATH instructions Homebrew prints, and re-run:"
  echo "  ./scripts/install-docker-cli-macos.sh"
  exit 1
fi

echo "==> Installing Colima, Docker CLI, and Docker Compose via Homebrew"
brew install colima docker docker-compose

echo "==> Starting Colima (local Docker VM)"
colima start --cpu 4 --memory 8

BREW_PREFIX="$(brew --prefix)"
export PATH="$BREW_PREFIX/bin:$PATH"
PLUGIN_DIR="$BREW_PREFIX/lib/docker/cli-plugins"
export PLUGIN_DIR
mkdir -p "$HOME/.docker/cli-plugins"

# Homebrew installs compose as a CLI plugin; stock Docker does not search Cellar by default.
if [[ -f "$PLUGIN_DIR/docker-compose" ]]; then
  ln -sf "$PLUGIN_DIR/docker-compose" "$HOME/.docker/cli-plugins/docker-compose"
  if command -v python3 >/dev/null; then
    python3 - <<'PY'
import json, os
from pathlib import Path
plugin_dir = os.environ["PLUGIN_DIR"]
path = Path.home() / ".docker" / "config.json"
cfg = {}
if path.exists():
    cfg = json.loads(path.read_text())
dirs = list(cfg.get("cliPluginsExtraDirs") or [])
if plugin_dir not in dirs:
    dirs.append(plugin_dir)
cfg["cliPluginsExtraDirs"] = dirs
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(cfg, indent=2) + "\n")
print(f"Updated {path} (cliPluginsExtraDirs)")
PY
  else
    echo "Add to ~/.docker/config.json:"
    echo "  \"cliPluginsExtraDirs\": [\"$PLUGIN_DIR\"]"
  fi
fi

echo ""
echo "Docker is ready:"
docker --version
docker compose version
echo ""
echo "Now run:  cd soroban-verify && make start"
