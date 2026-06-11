# CI/CD: deploy to AWS EC2 on push to `main`

This repo uses **GitHub Actions** to run tests and deploy to an **EC2** instance over SSH (same stack as `make ec2` / `make run`).

## How it works

```text
push to main
    → GitHub Actions: pytest
    → SSH to EC2: git pull + ./deploy/ec2/remote-deploy.sh
    → docker compose build (API + builder) + restart API
    → health check on http://127.0.0.1:8080/health
```

Put **nginx + HTTPS** in front of the app using [deploy/nginx/README.md](../nginx/README.md).

---

## 1. Launch EC2 (one-time)

| Setting | Recommendation |
|---------|----------------|
| AMI | Ubuntu 24.04 LTS |
| Instance | `t3.medium` or larger (builder image + verifications need RAM) |
| Disk | 30 GB+ |
| Security group | Inbound **22** (SSH), **80**, **443**; **8080** only if you skip nginx |

Create or import an **SSH key pair** and download the private key (`.pem`).

---

## 2. Bootstrap the server (one-time)

SSH in:

```bash
ssh -i your-key.pem ubuntu@<EC2_PUBLIC_IP>
```

On the server:

```bash
export REPO_URL="https://github.com/shilpachittara/SourceProof.git"
curl -fsSL https://raw.githubusercontent.com/shilpachittara/SourceProof/main/deploy/ec2/bootstrap-server.sh | bash
# Or after cloning manually:
# git clone https://github.com/shilpachittara/SourceProof.git ~/soroban-verify
# cd ~/soroban-verify && chmod +x deploy/ec2/*.sh && ./deploy/ec2/bootstrap-server.sh

newgrp docker   # or log out and back in
cd ~/soroban-verify
make build
./deploy/ec2/remote-deploy.sh
curl -s http://127.0.0.1:8080/health
```

For a **private** repo, clone with a deploy key or PAT on the server instead of the public `REPO_URL` curl.

---

## 3. GitHub repository secrets

In GitHub: **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Example | Required |
|--------|---------|----------|
| `EC2_HOST` | `54.12.34.56` or `sourceproof.example.com` | Yes |
| `EC2_USER` | `ubuntu` | Yes |
| `EC2_SSH_KEY` | Full contents of your `.pem` private key | Yes |
| `EC2_DEPLOY_PATH` | `/home/ubuntu/soroban-verify` | No (defaults to `$HOME/soroban-verify`) |
| `EC2_SSH_PORT` | `22` | No |

Optional: create a GitHub **environment** named `production` (Settings → Environments) to require approval before deploy.

---

## 4. Enable the workflow

Commit and push:

- `.github/workflows/ci.yml` — tests on PR and push
- `.github/workflows/deploy.yml` — deploy on push to `main`
- `deploy/ec2/remote-deploy.sh` — server-side deploy script

After the first push to `main`, open **Actions** in GitHub and confirm **Deploy to AWS EC2** succeeds.

---

## 5. Manual deploy (without waiting for CI)

On the EC2 host:

```bash
cd ~/soroban-verify
git pull origin main
./deploy/ec2/remote-deploy.sh
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Permission denied (publickey)` | Check `EC2_SSH_KEY` secret (full PEM, including `BEGIN/END` lines) |
| `not a git repo` | Clone the repo on EC2; set `EC2_DEPLOY_PATH` to that directory |
| `Docker daemon is not running` | `sudo systemctl start docker`; user in `docker` group |
| Deploy timeout | First builder build can take 10–30 min; workflow allows 45m |
| Verify fails after deploy | Run `docker compose --profile builder build builder` on server |
| Health check fails | `docker compose -f docker-compose.fast.yml logs api` |

---

## Alternative: ECR + ECS (not included)

For multi-instance or auto-scaling production, you would push images to **Amazon ECR** and run **ECS/Fargate**. This repo’s verifications require **Docker-out-of-docker** (host socket + builder image), which maps cleanly to a single EC2 (or one EC2 per verifier). Start with EC2 + this workflow; migrate to ECR when you need horizontal API scaling with a shared queue.
