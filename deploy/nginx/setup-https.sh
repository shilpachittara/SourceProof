#!/usr/bin/env bash
# Install nginx, proxy to SourceProof on :8080, obtain free Let's Encrypt cert.
#
# Prerequisites:
#   - Ubuntu/Debian, root via sudo
#   - DNS A record for DOMAIN → this server's public IP
#   - SourceProof already healthy: curl -s http://127.0.0.1:8080/health
#
# Usage:
#   sudo ./deploy/nginx/setup-https.sh sourceproof.upthrust.club admin@upthrust.club
set -euo pipefail

DOMAIN="${1:?Usage: setup-https.sh <domain> <email-for-letsencrypt>}"
EMAIL="${2:?Usage: setup-https.sh <domain> <email-for-letsencrypt>}"

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CONF_SRC="$ROOT/deploy/nginx/sourceproof.conf"
CONF_DST="/etc/nginx/sites-available/sourceproof"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi

if ! curl -sf "http://127.0.0.1:8080/health" >/dev/null 2>&1; then
  echo "SourceProof is not responding on http://127.0.0.1:8080/health"
  echo "Start it first from $ROOT: make ec2   (or make run)"
  exit 1
fi

echo "==> Installing nginx"
apt-get update -qq
apt-get install -y nginx certbot python3-certbot-nginx

echo "==> Installing site config for $DOMAIN"
sed "s/sourceproof.upthrust.club/${DOMAIN}/g" "$CONF_SRC" > "$CONF_DST"
ln -sf "$CONF_DST" /etc/nginx/sites-enabled/sourceproof
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl enable nginx
systemctl reload nginx

echo "==> Checking DNS (A record must point to this host)"
RESOLVED="$(dig +short "$DOMAIN" A | head -1 || true)"
echo "    $DOMAIN → ${RESOLVED:-<none>}"
if [[ -z "$RESOLVED" ]]; then
  echo "Warning: no A record yet. Certbot may fail until DNS propagates."
fi

echo "==> Requesting Let's Encrypt certificate (free)"
certbot --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --redirect --non-interactive

echo ""
echo "Done."
echo "  UI:     https://${DOMAIN}/demo/"
echo "  Health: https://${DOMAIN}/health"
echo "  API:    https://${DOMAIN}/v1/verify"
echo ""
echo "Renewal test: certbot renew --dry-run"
