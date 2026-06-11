#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu EC2 instance (run as your SSH user).
# Usage: curl -fsSL <raw-url> | bash   OR   ./deploy/ec2/bootstrap-server.sh
set -euo pipefail

REPO_URL="${REPO_URL:-}"
DEPLOY_DIR="${DEPLOY_DIR:-$HOME/soroban-verify}"

echo "==> Installing Docker + git…"
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin git curl
sudo usermod -aG docker "$USER" || true

if [[ -n "$REPO_URL" ]] && [[ ! -d "$DEPLOY_DIR/.git" ]]; then
  echo "==> Cloning $REPO_URL → $DEPLOY_DIR"
  git clone "$REPO_URL" "$DEPLOY_DIR"
fi

if [[ -d "$DEPLOY_DIR" ]]; then
  chmod +x "$DEPLOY_DIR"/scripts/*.sh "$DEPLOY_DIR"/deploy/ec2/*.sh 2>/dev/null || true
fi

echo ""
echo "✓ Bootstrap complete."
echo "  1. Log out and back in (or: newgrp docker) so docker group applies."
echo "  2. cd $DEPLOY_DIR && make build && ./deploy/ec2/remote-deploy.sh"
echo "  3. Open security group: TCP 22, 80, 443 (and 8080 only if not using nginx)."
echo "  4. Add GitHub Actions secrets: EC2_HOST, EC2_USER, EC2_SSH_KEY, EC2_DEPLOY_PATH=$DEPLOY_DIR"
