# Joplin Server

Self-hosted [Joplin Server](https://github.com/laurent22/joplin) running via Docker Compose on a local Ubuntu machine, exposed publicly through a Cloudflare Tunnel at [joplin.kalp.dev](https://joplin.kalp.dev).

## Stack

| Component | Details |
|---|---|
| **Joplin Server** | `joplin/server:latest` |
| **Database** | PostgreSQL 16 |
| **Reverse proxy / TLS** | Cloudflare Tunnel (`cloudflared`) |
| **Public URL** | `https://joplin.kalp.dev` |

## Prerequisites

- Docker + Docker Compose
- [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/get-started/) configured with a tunnel routing `joplin.kalp.dev → localhost:22300`
- [`rclone`](https://rclone.org/install/) configured with a Google Drive remote named `gdrive`

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/Kalp-S/joplin-server.git
cd joplin-server
```

### 2. Create your `.env` file

Copy the example and fill in your values:

```bash
cp .env.example .env
```

`.env` variables:

```env
# PostgreSQL
POSTGRES_DB=joplin
POSTGRES_USER=joplin
POSTGRES_PASSWORD=your-strong-password-here

# Joplin Server
APP_PORT=22300
APP_BASE_URL=https://joplin.kalp.dev
DB_CLIENT=pg
POSTGRES_HOST=joplin-db
POSTGRES_PORT=5432
POSTGRES_DATABASE=joplin

# Mailer (optional)
MAILER_ENABLED=0
```

### 3. Start the server

```bash
docker compose up -d
docker compose logs -f   # watch startup
```

Joplin will be live at **https://joplin.kalp.dev**.

**Default credentials (change immediately after first login):**
- Email: `admin@localhost`
- Password: `admin`

## Connecting Joplin Clients

1. Open Joplin desktop or mobile app
2. Go to **Settings → Synchronisation**
3. Set sync target to **Joplin Server**
4. Server URL: `https://joplin.kalp.dev`
5. Sign in with your account credentials

## Backup & Restore

Backups include a full PostgreSQL dump + config files, stored in Google Drive (`gdrive:joplin backups`). A systemd timer runs `backup.sh` daily at **2:00 AM**.

### Run a manual backup

```bash
./backup.sh
```

### Restore from a backup

```bash
./restore.sh               # interactive — lists Drive backups, you pick one
./restore.sh ./backups/joplin-backup-2026-06-27_21-23-41.tar.gz  # direct file
```

> **Note:** Restore will prompt you to type `YES` before dropping the database.

### Check backup timer status

```bash
systemctl list-timers joplin-backup.timer
journalctl -u joplin-backup.service -n 50
```

## Useful Commands

```bash
# View live logs
docker compose logs -f

# Restart
docker compose restart

# Stop
docker compose down

# Update to latest Joplin version
docker compose pull && docker compose up -d
```

## Cloudflare Tunnel Config

Managed in `/etc/cloudflared/config.yml` on the host machine:

```yaml
tunnel: <tunnel-id>
credentials-file: /home/kalp/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: kalp.dev
    service: http://localhost:2368   # Ghost blog
  - hostname: joplin.kalp.dev
    service: http://localhost:22300  # Joplin Server
  - service: http_status:404
```

```bash
# Restart tunnel after config changes
sudo systemctl restart cloudflared
```

## File Structure

```
.
├── docker-compose.yml   # Service definitions
├── .env                 # Secrets & config (gitignored)
├── backup.sh            # Daily backup script
├── restore.sh           # Interactive restore script
├── backups/             # Local backup archives (gitignored)
└── db/                  # PostgreSQL data volume (gitignored)
```
