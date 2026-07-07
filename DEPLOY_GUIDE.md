# BUGSIFT v0.2.0 Self-Hosted Deployment Guide

**Self-hosted by design.** This guide walks you through deploying bugsift to your infrastructure and accessing it via your own domain.

---

## Quick Summary

| Item | Details |
|------|---------|
| **What you get** | Full bugsift stack (Backend, Frontend, Database, Cache) |
| **Where it runs** | Your server (AWS, DigitalOcean, on-premise, etc.) |
| **Your domain** | `bugsift.yourdomain.com` or any domain you own |
| **Time to deploy** | 5 minutes (with installer) |
| **Data location** | Entirely in your infrastructure |
| **Cost** | Server costs only, no SaaS fees |

---

## Prerequisites

### Server Requirements
- **OS:** Linux (Ubuntu 20.04+, Debian 11+) or macOS
- **Docker:** v20+ with Docker Compose
- **RAM:** 2GB minimum (4GB recommended for production)
- **Disk:** 10GB minimum
- **Network:** Outbound HTTPS access to pull images

### You'll Need
1. **A domain name** — e.g., `bugsift.mycompany.com` (optional for testing, required for production)
2. **SSH access to your server**
3. **GitHub Personal Access Token** (for bugsift to access your repos)

---

## Deployment Steps

### Step 1: Prepare Your Server

```bash
# SSH into your server
ssh user@your-server.com

# Update system packages
sudo apt-get update && sudo apt-get upgrade -y

# Install Docker (if not already installed)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Add your user to docker group (optional, avoid sudo)
sudo usermod -aG docker $USER
newgrp docker
```

### Step 2: Deploy BUGSIFT

```bash
# Deploy with default settings (localhost access for testing)
BUGSIFT_IMAGE_TAG=v0.2.0 \
  curl -fsSL https://github.com/joym-gits/bugsift/releases/download/v0.2.0/install.sh | bash

# After successful installation, you'll see:
# ✅ Generated .env with secure secrets
# ✅ Pulled pre-built images from GHCR
# ✅ Created PostgreSQL database
# ✅ Created Redis cache
# ✅ Started all services

# View status:
docker compose ps
```

### Step 3: Access BUGSIFT (Initial Testing)

**For local testing only:**
```bash
# If accessing from your server directly:
curl http://localhost:8080

# If accessing from your machine:
# SSH port forward:
ssh -L 8080:localhost:8080 user@your-server.com
# Then visit: http://localhost:8080 in your browser
```

### Step 4: Configure Your Domain (Production)

#### Option A: Using Your Own Domain (Recommended)

```bash
# 1. Point your domain to your server's IP
# In your domain registrar's DNS settings:
# A record: bugsift.yourdomain.com → your-server-ip

# 2. Update bugsift configuration
ssh user@your-server.com

# Edit .env file:
nano .env

# Add/update these lines:
DOMAIN=bugsift.yourdomain.com
ENVIRONMENT=production
DEBUG=false

# 3. Restart services with new config:
docker compose restart

# 4. Access at your domain:
# http://bugsift.yourdomain.com:8080
```

#### Option B: Using Caddy for Automatic TLS (HTTPS)

```bash
# 1. Install Caddy on your server
sudo apt-get install -y caddy

# 2. Create Caddyfile
sudo nano /etc/caddy/Caddyfile

# Add this configuration:
bugsift.yourdomain.com {
  reverse_proxy localhost:8080
}

# 3. Start Caddy
sudo systemctl restart caddy

# 4. Access with automatic HTTPS:
# https://bugsift.yourdomain.com
```

#### Option C: Using Let's Encrypt with Nginx (Already Installed)

The installer includes Nginx. Configure it for TLS:

```bash
# 1. Get a Let's Encrypt certificate:
sudo certbot certonly --standalone \
  -d bugsift.yourdomain.com

# 2. Update Nginx config:
# Edit: docker-compose.yml or nginx/nginx.conf
# Point to your certificate

# 3. Restart Nginx:
docker compose restart nginx
```

---

## After Deployment

### Bootstrap Your Installation

```bash
# Get your bootstrap token from installation output:
# It will be displayed in the installer output

# Or retrieve it from .env:
grep BOOTSTRAP_TOKEN .env

# Use this token to:
1. Log in for the first time
2. Create your admin account
3. Connect your GitHub repositories
```

### Configure GitHub Integration

```bash
# 1. Create a GitHub App
# Visit: https://github.com/settings/apps/new

# 2. Set webhook URL to:
# https://bugsift.yourdomain.com/webhook

# 3. Install the app on your repositories

# 4. Add the credentials to bugsift via the web UI
```

### Verify Everything Works

```bash
# Check all services are healthy:
docker compose ps

# Should show:
# ✅ backend (running)
# ✅ frontend (running)
# ✅ postgres (healthy)
# ✅ redis (healthy)
# ✅ nginx (running)

# View logs:
docker compose logs -f
```

---

## Data & Backups

### Database Backups

```bash
# Backup PostgreSQL
docker compose exec postgres pg_dump -U postgres bugsift > backup.sql

# Restore from backup
docker compose exec -T postgres psql -U postgres < backup.sql
```

### Volume Backups

```bash
# Your data is stored in Docker volumes
docker volume ls | grep bugsift

# Backup a volume:
docker run --rm -v bugsift_postgres_data:/data \
  -v $(pwd):/backup \
  ubuntu tar czf /backup/postgres-backup.tar.gz -C /data .
```

---

## Upgrading to New Versions

```bash
# Update to a new version:
BUGSIFT_IMAGE_TAG=v0.3.0 \
  curl -fsSL https://github.com/joym-gits/bugsift/releases/download/v0.3.0/install.sh | bash

# The installer will:
# ✅ Pull new images
# ✅ Run migrations
# ✅ Restart services
# ✅ Preserve all your data
```

---

## Troubleshooting

### Services won't start

```bash
# Check logs:
docker compose logs

# Restart all services:
docker compose restart

# Full reset (careful!):
docker compose down
docker compose up -d
```

### Can't access from your domain

```bash
# Check DNS resolution:
nslookup bugsift.yourdomain.com

# Check firewall:
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 8080/tcp

# Test connectivity:
curl http://your-server-ip:8080
```

### Out of disk space

```bash
# Check disk usage:
df -h

# Clean up Docker
docker system prune -a

# Expand volume (cloud provider specific)
```

### Forgot bootstrap token

```bash
# Reset bootstrap token:
docker compose exec backend python -m bugsift.cli reset-token

# Copy the new token from output
```

---

## Architecture Overview

```
Your Domain: bugsift.yourdomain.com
                    ↓
            Nginx Reverse Proxy
                    ↓
        ┌───────────┬───────────┐
        ↓           ↓
    Backend       Frontend
    (FastAPI)     (Next.js)
        ↓           ↓
    PostgreSQL    Redis
    (Database)    (Cache)
        ↓
    GitHub API
    (Read-only)
```

**All data stays within your infrastructure.**

---

## Performance Tuning

### For High Volume (100+ repos)

```bash
# In docker-compose.yml, increase resources:
services:
  backend:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G

  postgres:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
```

### Monitor Resource Usage

```bash
# Real-time stats:
docker stats

# Historical data (with metrics backend):
docker compose logs -f backend | grep "memory"
```

---

## Security Hardening

### Production Checklist

- ✅ Use HTTPS (Caddy or Let's Encrypt)
- ✅ Set `DEBUG=false` in .env
- ✅ Use strong database passwords
- ✅ Enable firewall (UFW, Security Groups, etc.)
- ✅ Restrict GitHub token scopes (minimal permissions)
- ✅ Regular backups
- ✅ Keep Docker images updated
- ✅ Monitor logs for errors

### Firewall Rules

```bash
# Allow only necessary ports:
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 80/tcp    # HTTP
sudo ufw allow 443/tcp   # HTTPS
sudo ufw deny 8080/tcp   # Block direct access to internal proxy
```

---

## Getting Help

- **Documentation:** [README.md](README.md)
- **Issues:** [GitHub Issues](https://github.com/joym-gits/bugsift/issues)
- **Discussions:** [GitHub Discussions](https://github.com/joym-gits/bugsift/discussions)

---

## What's Next?

1. ✅ Deploy bugsift to your infrastructure
2. ✅ Configure your domain
3. ✅ Connect your GitHub repositories
4. ✅ Set up triage workflows
5. ✅ Let the AI learn from your team's decisions

**Your infrastructure. Your data. Your rules.** 🚀
