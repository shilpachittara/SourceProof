# Deploy SourceProof with nginx + free HTTPS (Let's Encrypt)

Use this on a Linux server (Ubuntu 22.04/24.04) with a public IP and domain **`sourceproof.upthrust.club`** pointing at that IP.

## URLs after setup

| What | URL |
|------|-----|
| Demo UI | https://sourceproof.upthrust.club/demo/ |
| API root | https://sourceproof.upthrust.club |
| Health | https://sourceproof.upthrust.club/health |
| OpenAPI | https://sourceproof.upthrust.club/docs |

---

## 1. DNS (do this first)

At your DNS provider for `upthrust.club`:

| Type | Name | Value |
|------|------|--------|
| A | `sourceproof` | `<SERVER_PUBLIC_IP>` |

Wait until it resolves:

```bash
dig +short sourceproof.upthrust.club
# must show your server IP
```

---

## 2. Start SourceProof (Docker)

On the server:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin git curl
sudo usermod -aG docker "$USER"
# log out and back in, or: newgrp docker

git clone <your-repo-url> soroban-verify
cd soroban-verify
make ec2
curl -s http://127.0.0.1:8080/health
```

`make ec2` = build images + run API/UI on port **8080** (localhost only recommended after nginx is up).

---

## 3. Install nginx

```bash
sudo apt-get install -y nginx
```

Copy the site config (edit `server_name` if your domain differs):

```bash
cd soroban-verify
sudo cp deploy/nginx/sourceproof.conf /etc/nginx/sites-available/sourceproof
sudo ln -sf /etc/nginx/sites-available/sourceproof /etc/nginx/sites-enabled/sourceproof
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl reload nginx
```

Open firewall / security group: **TCP 80** and **TCP 443** (and **22** for SSH).

Test HTTP (before SSL):

```bash
curl -s http://sourceproof.upthrust.club/health
```

---

## 4. Free SSL certificate (Let's Encrypt via Certbot)

Certbot is free, auto-renews, and trusted by browsers.

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d sourceproof.upthrust.club
```

Certbot will ask for:

- **Email** — for expiry notices (required)
- **Terms** — agree
- **Redirect HTTP → HTTPS** — choose **Yes** (recommended)

Test HTTPS:

```bash
curl -s https://sourceproof.upthrust.club/health
```

Browser: **https://sourceproof.upthrust.club/demo/**

Renewal is automatic (systemd timer). Check:

```bash
sudo certbot renew --dry-run
```

---

## 5. Lock down port 8080 (optional)

So only nginx is public, edit `docker-compose.fast.yml`:

```yaml
ports:
  - "127.0.0.1:8080:8080"
```

Then:

```bash
make down
make run
```

---

## 6. Proxy headers (recommended behind HTTPS)

So API links use `https://`, add under `api` in `docker-compose.fast.yml`:

```yaml
command: ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
```

Then `make down && make run`.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Certbot fails “connection” | DNS not propagated; port 80 blocked; nginx not running |
| 502 Bad Gateway | SourceProof down — `curl http://127.0.0.1:8080/health`, `make run` |
| Upload fails | `client_max_body_size 55m` in nginx config (already in template) |
| Verify build fails | `make builder` then retry; check `make logs` |
| Wrong links in API (`http://`) | Add uvicorn `--proxy-headers` (step 6) |

---

## One-shot helper script

From repo root on the server (after DNS + `make ec2`):

```bash
sudo ./deploy/nginx/setup-https.sh sourceproof.upthrust.club your@email.com
```

See `setup-https.sh` for what it automates.
