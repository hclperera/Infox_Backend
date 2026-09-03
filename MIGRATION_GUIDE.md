# InfoX Backend — Server Migration Guide

If you ever need to move this backend to a brand new Ubuntu Linux VM, follow these exact steps to recreate the environment perfectly.

> [!IMPORTANT]
> This guide reflects the **current production setup** as of 4th September 2026.
> The domain `server.projectinfox.tech` is used instead of a raw IP. HTTPS is handled end-to-end using a Cloudflare Origin Certificate with SSL mode "Full (Strict)". Nginx acts as a reverse proxy on ports 80 and 443.

---

## 1. Install System Dependencies

Update the new server and install Python, MySQL, Nginx, and the GitHub CLI tool (`gh`).

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv mysql-server nginx gh -y
```

---

## 2. Authenticate with GitHub

Log in to GitHub so you can clone the private repository securely.

```bash
gh auth login
# Follow the prompts:
# - What account do you want to log into? GitHub.com
# - What is your preferred protocol? HTTPS
# - Authenticate Git with your GitHub credentials? Yes
# - Login with a web browser
```

---

## 3. Clone Repository & Setup Environment

Clone the code and install all the Python libraries exactly as they were on the old server.

```bash
git clone https://github.com/hclperera/Infox_Backend.git infox-backend
cd infox-backend

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install exact dependencies
pip install -r requirements.txt
```

---

## 4. Setup MySQL Database

Log into the MySQL root console:

```bash
sudo mysql
```

Run these SQL commands to recreate the database and user:

```sql
CREATE DATABASE infox_db;
CREATE USER 'raven'@'localhost' IDENTIFIED BY 'InfoxDB100200!';
GRANT ALL PRIVILEGES ON infox_db.* TO 'raven'@'localhost';
FLUSH PRIVILEGES;
EXIT;
```

Apply the schema (creates `users`, `settings`, `audit_logs` tables and triggers):

```bash
mysql -u raven -p infox_db < /home/raven/infox-backend/db/schema.sql
```

> [!NOTE]
> `schema.sql` already includes the `audit_logs` table and immutability triggers.
> **Do not run `migrate_audit_logs.sql` on a fresh VM** — that file only exists to upgrade an already-running database that was set up before audit logs were added.

### When to use `migrate_audit_logs.sql`

Only run this on an **existing production database** that is missing the `audit_logs` table:

```bash
# Only for existing DBs — NOT needed on fresh installs
mysql -u raven -p infox_db < /home/raven/infox-backend/db/migrate_audit_logs.sql
```

### Verify tables were created

```bash
mysql -u raven -p -D infox_db -e "SHOW TABLES;"
```

Expected output:

```
+--------------------+
| Tables_in_infox_db |
+--------------------+
| audit_logs         |
| settings           |
| users              |
+--------------------+
```

---

## 5. Recreate the `.env` File

Because `.env` is ignored by Git, you must create it manually on the new server.

```bash
nano /home/raven/infox-backend/.env
```

Paste in all credentials (get the real values from the old server or your password manager):

```env
DB_HOST=localhost
DB_USER=raven
DB_PASSWORD=InfoxDB100200!
DB_NAME=infox_db

# Admin Panel Credentials
ADMIN_USERNAME=<copy from old server>
ADMIN_PASSWORD=<copy from old server>
ADMIN_SECRET_KEY=<copy from old server>
```

> [!CAUTION]
> Never commit `.env` to Git. It is already in `.gitignore`.

---

## 6. Setup the Systemd Background Service

To make the FastAPI app run in the background and start on boot, create the systemd service.

> [!IMPORTANT]
> FastAPI must bind to `127.0.0.1` (localhost only), **NOT** `0.0.0.0`. Nginx handles all public traffic. Exposing port 8000 directly to the internet would bypass SSL and the Azure NSG deny rule.

```bash
sudo nano /etc/systemd/system/infox_api.service
```

Paste in the exact configuration:

```ini
[Unit]
Description=InfoX FastAPI Backend Service
After=network.target mysql.service

[Service]
User=raven
WorkingDirectory=/home/raven/infox-backend
ExecStart=/home/raven/infox-backend/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable infox_api
sudo systemctl start infox_api
sudo systemctl status infox_api  # Verify it's running
```

---

## 7. Setup SSL Certificate (Cloudflare Origin Certificate)

The server uses a **Cloudflare Origin Certificate** for end-to-end HTTPS. This is free and valid for 15 years.

**A. Generate in Cloudflare:**
1. Go to Cloudflare → `projectinfox.tech` → **SSL/TLS → Origin Server**
2. Click **"Create Certificate"**
3. Hostnames: `projectinfox.tech`, `*.projectinfox.tech` — Validity: **15 years**
4. Copy the **Origin Certificate** and **Private Key** (shown only once!)

**B. Upload to the server:**

```bash
sudo mkdir -p /etc/ssl/cloudflare
sudo nano /etc/ssl/cloudflare/origin.pem   # paste the certificate
sudo nano /etc/ssl/cloudflare/origin.key   # paste the private key
sudo chmod 600 /etc/ssl/cloudflare/origin.key
sudo chmod 644 /etc/ssl/cloudflare/origin.pem
```

---

## 8. Setup Nginx Reverse Proxy

Nginx sits in front of FastAPI, handles ports 80 and 443, and terminates SSL using the Cloudflare Origin Certificate.

> [!IMPORTANT]
> The `/scan` location block uses extended timeouts and a larger upload limit. This is required because the ML pipeline (YOLO page detection + dot segmentation) can take up to 90 seconds, and the Flutter app sends full-resolution JPEG images that can exceed Nginx's default 1MB body limit.
>
> **Note:** The `/scan` endpoint is not yet implemented — this config is pre-configured so Nginx is ready when it is built.

```bash
sudo tee /etc/nginx/sites-available/server.projectinfox.tech > /dev/null << 'EOF'
# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name server.projectinfox.tech;
    return 301 https://$host$request_uri;
}

# HTTPS server
server {
    listen 443 ssl;
    server_name server.projectinfox.tech;

    ssl_certificate     /etc/ssl/cloudflare/origin.pem;
    ssl_certificate_key /etc/ssl/cloudflare/origin.key;

    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # ── Standard routes (auth, profile, etc.) ─────────────────────────────
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # Standard timeouts for fast endpoints
        proxy_connect_timeout 60s;
        proxy_send_timeout    60s;
        proxy_read_timeout    60s;
    }

    # ── /scan — Braille image upload + ML pipeline ─────────────────────────
    # Extended limits because:
    #   • Flutter sends full-resolution JPEG (can be 5–15 MB)
    #   • YOLOv8 + dot segmentation inference can take up to 90 seconds
    location /scan {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Allow image uploads up to 20 MB
        client_max_body_size 20M;

        # Extended timeouts for model inference
        proxy_connect_timeout 120s;
        proxy_send_timeout    120s;
        proxy_read_timeout    120s;
    }
}
EOF
```

Enable the site and reload Nginx:

```bash
sudo ln -s /etc/nginx/sites-available/server.projectinfox.tech /etc/nginx/sites-enabled/
sudo nginx -t          # Must say "syntax ok"
sudo systemctl reload nginx
sudo systemctl enable nginx
```

---

## 9. Azure Network Security Group (NSG) Rules

In the Azure Portal → VM → Networking → Inbound port rules, ensure these rules exist:

| Priority | Name | Port | Action |
|----------|------|------|--------|
| 300 | Allow-SSH | 22 | Allow |
| 310 | Allow-HTTP | 80 | Allow |
| 315 | Allow-HTTPS | 443 | Allow |
| 320 | Deny-FastAPI | 8000 | **Deny** |

> [!NOTE]
> Port 443 must be open because Cloudflare "Full (Strict)" mode connects to the server over HTTPS.
> Port 8000 must be **Denied** so FastAPI is never accessible directly from the internet.

---

## 10. Cloudflare DNS Setup

1. Log in to [dash.cloudflare.com](https://dash.cloudflare.com)
2. Go to `projectinfox.tech` → **DNS → Records**
3. Add the A record for the API server:

| Type | Name | IPv4 | Proxy |
|------|------|------|-------|
| `A` | `server` | `<new VM public IP>` | ☁️ Proxied |

4. Add the CNAME for the admin panel (Vercel):

| Type | Name | Target | Proxy |
|------|------|--------|-------|
| `CNAME` | `admin` | `<value from Vercel>` | ⚪ DNS Only |

5. Go to **SSL/TLS** tab → set mode to **"Full (Strict)"**

> [!IMPORTANT]
> If you get a new VM with a different public IP, you only need to update the `server` A record in Cloudflare.
> The Cloudflare Origin Certificate must already be on the server (Step 7) before setting "Full (Strict)".

---

## 11. Setup Automated Deployments (Auto-Updater)

The `deploy.sh` script pulls from GitHub every minute and restarts the service on changes.

**A. Make the scripts executable:**

```bash
chmod +x /home/raven/infox-backend/scripts/deploy.sh
chmod +x /home/raven/infox-backend/scripts/restart.sh
```

**B. Grant passwordless sudo to restart the service:**

```bash
echo "raven ALL=(ALL) NOPASSWD: /bin/systemctl restart infox_api.service" | sudo tee /etc/sudoers.d/infox_api_restart
sudo chmod 0440 /etc/sudoers.d/infox_api_restart
```

**C. Schedule the Cron Job:**

```bash
crontab -e
```

Add this line to the very bottom:

```bash
* * * * * /home/raven/infox-backend/scripts/deploy.sh >> /home/raven/infox-backend/auto_update.log 2>&1
```

---

## 12. Verify CORS in main.py

The CORS config in `main.py` is already correct (it's in Git). Confirm it contains:

```python
allow_origins=[
    "http://localhost:3000",                    # Next.js local dev
    "https://infox-admin-alpha.vercel.app",     # Vercel preview deployments
    "https://admin.projectinfox.tech",          # Custom admin domain
],
```

> [!NOTE]
> Do **NOT** add `server.projectinfox.tech` to CORS — that is the API itself, not a frontend.

---

## ✅ Migration Checklist

- [ ] Install dependencies (Python, MySQL, Nginx, gh)
- [ ] Authenticate GitHub (`gh auth login`) and clone repo
- [ ] Create virtual environment and install packages
- [ ] Setup MySQL database and user
- [ ] Apply `schema.sql` to create all tables
- [ ] Create `.env` file with all credentials
- [ ] Create and enable `infox_api.service` (with `--host 127.0.0.1`)
- [ ] Generate Cloudflare Origin Certificate (15 years) and upload to `/etc/ssl/cloudflare/`
- [ ] Create and enable Nginx config:
  - [ ] HTTP → HTTPS redirect
  - [ ] HTTPS with Cloudflare Origin Certificate
  - [ ] Standard `/` location (60s timeouts)
  - [ ] `/scan` location (`client_max_body_size 20M`, 120s timeouts)
- [ ] Update Azure NSG: Allow 80, Allow 443, Deny 8000
- [ ] Update Cloudflare `server` A record to new VM IP
- [ ] Set Cloudflare SSL mode to **"Full (Strict)"**
- [ ] Setup auto-updater (`deploy.sh` + cron, runs every minute)
- [ ] Verify CORS in `main.py` includes `admin.projectinfox.tech`
- [ ] Add `admin.projectinfox.tech` custom domain in Vercel
- [ ] Verify: `https://server.projectinfox.tech` returns `{"status": "InfoX API is online and modular!"}`
- [ ] Verify: `https://admin.projectinfox.tech` login works
- [ ] **[When /scan is built]** Test `POST /scan` with a sample JPEG — confirm 200 response within 90s

### You are done! 🎉

---

## Appendix — Quick Reference

| Task | Command |
|------|---------|
| Restart API | `bash ~/infox-backend/scripts/restart.sh` |
| View live logs | `journalctl -u infox_api -f` |
| Check Nginx config | `sudo nginx -t` |
| Reload Nginx | `sudo systemctl reload nginx` |
| Activate venv | `source ~/infox-backend/venv/bin/activate` |
| Install deps | `pip install -r requirements.txt` |
| Check DB | `mysql -u raven -p -D infox_db` |
| View auto-deploy log | `tail -f ~/infox-backend/auto_update.log` |
| Health check | `curl https://server.projectinfox.tech/` |

---

## Appendix — Why `migrate_audit_logs.sql` Exists

`schema.sql` already contains everything needed on a fresh install. `migrate_audit_logs.sql` was written as an **incremental migration** to add the `audit_logs` table to an existing production database that was set up before that feature was implemented. Only run it on a live DB that is missing the `audit_logs` table.
