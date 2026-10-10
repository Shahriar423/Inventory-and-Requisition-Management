#!/usr/bin/env bash
# =============================================================================
#  IRM - one-shot installer for Ubuntu Server 22.04 / 24.04 (VMware VM or any Linux box)
#
#  What it sets up:  MongoDB  +  FastAPI backend (systemd service)  +  React build served by Nginx
#                    firewall, nightly database backup, first Super Admin.
#  Re-run it any time to deploy an update (code is re-synced, frontend rebuilt, service restarted).
#
#  Usage (from the cloned repository):
#      sudo bash deploy/setup.sh                 # asks a few questions
#      sudo bash deploy/setup.sh --https         # also create a self-signed HTTPS certificate
#      sudo SERVER_NAME=192.168.1.50 ADMIN_EMAIL=me@corp.com ADMIN_PASSWORD='S3cret-pass' \
#           bash deploy/setup.sh --yes           # no questions (for automation)
#
#  Options:   --server NAME   IP address or host name users will type (default: this machine's IP)
#             --https         serve over HTTPS with a self-signed certificate
#             --http          serve over plain HTTP (default)
#             --no-build      skip the frontend build and reuse the current website files
#             --yes           never ask questions (all values must come from the environment)
#             --help
# =============================================================================
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/irm}"
WEB_ROOT="${WEB_ROOT:-/var/www/irm}"
DB_NAME="${DB_NAME:-it_requisition_db}"
SERVICE_USER="irm"
BACKEND_PORT=8001
BACKUP_DIR="/var/backups/irm"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SERVER_NAME="${SERVER_NAME:-}"
ENABLE_HTTPS="${ENABLE_HTTPS:-}"      # yes | no
DO_BUILD=1
ASSUME_YES=0

log()  { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;31m[!] %s\033[0m\n' "$*" >&2; }
die()  { warn "$*"; exit 1; }
is_tty() { [[ -t 0 && "$ASSUME_YES" -eq 0 ]]; }

usage() { sed -n '2,24p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

# --------------------------------------------------------------------------- helpers
# set_env FILE KEY VALUE  - replaces or adds KEY='VALUE' (single-quoted so special characters are safe)
set_env() {
  local f="$1" k="$2" v="$3"
  [[ "$v" == *"'"* || "$v" == *$'\n'* ]] && die "Value for $k must not contain a single quote or a line break."
  touch "$f"
  grep -v "^${k}=" "$f" > "$f.tmp" || true
  printf "%s='%s'\n" "$k" "$v" >> "$f.tmp"
  mv "$f.tmp" "$f"
}
unset_env() { local f="$1" k="$2"; [[ -f "$f" ]] && { grep -v "^${k}=" "$f" > "$f.tmp" || true; mv "$f.tmp" "$f"; }; return 0; }
has_env()   { grep -q "^$2=" "$1" 2>/dev/null; }
rand_secret() { openssl rand -base64 48 | tr -d '\n=+/' | cut -c1-48; }
rand_pass()   { openssl rand -base64 18 | tr -d '\n=+/' | cut -c1-14; }
is_ip() { [[ "$1" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]]; }

# render_nginx SERVER_NAME HTTPS(yes|no)  -> prints the nginx site config
render_nginx() {
  local sn="$1" https="$2"
  local common
  common=$(cat <<EOF
    root ${WEB_ROOT};
    index index.html;
    client_max_body_size 25M;

    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml;
    add_header X-Content-Type-Options nosniff;

    # API (FastAPI)
    location /api/ {
        proxy_pass http://127.0.0.1:${BACKEND_PORT};
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }

    # Built React files (hashed names, safe to cache for a long time)
    location /static/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
        add_header X-Content-Type-Options nosniff;
    }

    # index.html must never be cached, so a new deployment shows up immediately
    location = /index.html {
        add_header Cache-Control "no-store";
    }

    # Single-page app: unknown paths (for example a refreshed /organization/users) fall back to index.html
    location / {
        try_files \$uri /index.html;
    }
EOF
)
  if [[ "$https" == "yes" ]]; then
    cat <<EOF
server {
    listen 80;
    server_name ${sn};
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    server_name ${sn};
    ssl_certificate     /etc/ssl/irm/irm.crt;
    ssl_certificate_key /etc/ssl/irm/irm.key;
    ssl_protocols TLSv1.2 TLSv1.3;
${common}
}
EOF
  else
    cat <<EOF
server {
    listen 80;
    server_name ${sn};
${common}
}
EOF
  fi
}

render_service() {
  cat <<EOF
[Unit]
Description=IRM backend (FastAPI)
After=network.target mongod.service
Wants=mongod.service

[Service]
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${APP_DIR}/backend
# One worker only: the approval-reminder job runs inside each worker and would repeat otherwise.
ExecStart=${APP_DIR}/backend/.venv/bin/uvicorn server:app --host 127.0.0.1 --port ${BACKEND_PORT}
Restart=always
RestartSec=3
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF
}

# --------------------------------------------------------------------------- steps
preflight() {
  [[ $EUID -eq 0 ]] || die "Run as root:  sudo bash deploy/setup.sh"
  [[ -f "$SRC_DIR/backend/server.py" && -f "$SRC_DIR/frontend/package.json" ]] \
    || die "Run this script from inside the cloned repository (expected backend/ and frontend/ next to deploy/)."
  # shellcheck disable=SC1091
  . /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]] || die "This script supports Ubuntu 22.04 / 24.04 only (found: ${PRETTY_NAME:-unknown})."
  case "${VERSION_CODENAME:-}" in jammy|noble) UBUNTU_CODENAME="$VERSION_CODENAME" ;;
    *) die "Unsupported Ubuntu release '${VERSION_CODENAME:-?}'. Use 22.04 (jammy) or 24.04 (noble)." ;; esac
  grep -qw avx /proc/cpuinfo || warn "CPU 'avx' flag not visible. MongoDB 5+ may crash on this VM. In VMware use a newer hardware version / expose host CPU features."
  local mem_mb; mem_mb=$(awk '/MemTotal/{print int($2/1024)}' /proc/meminfo)
  (( mem_mb >= 1800 )) || warn "Only ${mem_mb} MB RAM. The frontend build needs about 2 GB; give the VM more memory or use --no-build with a prebuilt frontend."
}

gather_config() {
  local detected; detected=$(hostname -I 2>/dev/null | awk '{print $1}')
  if [[ -z "$SERVER_NAME" ]]; then
    if is_tty; then read -rp "Address users will open (IP or host name) [${detected}]: " SERVER_NAME; fi
    SERVER_NAME="${SERVER_NAME:-$detected}"
  fi
  [[ -n "$SERVER_NAME" ]] || die "Could not detect an address. Pass --server NAME."
  if [[ -z "$ENABLE_HTTPS" ]]; then
    if is_tty; then read -rp "Use HTTPS with a self-signed certificate? [y/N]: " a; [[ "${a,,}" == y* ]] && ENABLE_HTTPS=yes || ENABLE_HTTPS=no
    else ENABLE_HTTPS=no; fi
  fi
  if [[ "$ENABLE_HTTPS" == "yes" ]]; then BASE_URL="https://${SERVER_NAME}"; else BASE_URL="http://${SERVER_NAME}"; fi

  if [[ ! -f "$APP_DIR/.setup_done" ]]; then
    if [[ -z "${ADMIN_EMAIL:-}" ]] && is_tty; then read -rp "First Super Admin email: " ADMIN_EMAIL; fi
    if [[ -z "${ADMIN_NAME:-}" ]]; then
      if is_tty; then read -rp "First Super Admin name [System Admin]: " ADMIN_NAME; fi
      ADMIN_NAME="${ADMIN_NAME:-System Admin}"
    fi
    if [[ -z "${ADMIN_PASSWORD:-}" ]] && is_tty; then
      local p1 p2
      read -rsp "Super Admin password (min 8 characters): " p1; echo
      read -rsp "Repeat password: " p2; echo
      [[ "$p1" == "$p2" ]] || die "Passwords do not match."
      ADMIN_PASSWORD="$p1"
    fi
    [[ "${ADMIN_EMAIL:-}" == *@* ]] || die "ADMIN_EMAIL is required (a valid email)."
    [[ -n "${ADMIN_PASSWORD:-}" && ${#ADMIN_PASSWORD} -ge 8 ]] || die "ADMIN_PASSWORD is required (at least 8 characters)."
  fi
  info "Address: ${BASE_URL}   |   Database: ${DB_NAME}   |   App folder: ${APP_DIR}"
}

install_packages() {
  log "Installing system packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y
  apt-get install -y python3 python3-venv python3-pip build-essential nginx ufw rsync curl gnupg openssl ca-certificates
}

install_mongo() {
  log "Installing MongoDB 8.0"
  if ! command -v mongod >/dev/null 2>&1; then
    curl -fsSL https://www.mongodb.org/static/pgp/server-8.0.asc | gpg --dearmor --yes -o /usr/share/keyrings/mongodb-server-8.0.gpg
    echo "deb [signed-by=/usr/share/keyrings/mongodb-server-8.0.gpg] https://repo.mongodb.org/apt/ubuntu ${UBUNTU_CODENAME}/mongodb-org/8.0 multiverse" \
      > /etc/apt/sources.list.d/mongodb-org-8.0.list
    apt-get update -y
    apt-get install -y mongodb-org
  else
    info "MongoDB already installed"
  fi
  systemctl enable --now mongod
  sleep 3
  systemctl is-active --quiet mongod || { journalctl -u mongod -n 20 --no-pager || true; die "MongoDB did not start. If the log says 'illegal instruction', the VM CPU lacks AVX (see the AVX warning above)."; }
}

install_node() {
  (( DO_BUILD )) || return 0
  log "Checking Node.js (needed once to build the frontend)"
  local major=0
  command -v node >/dev/null 2>&1 && major=$(node -p 'process.versions.node.split(".")[0]')
  if (( major < 18 )); then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
  fi
  command -v yarn >/dev/null 2>&1 || npm install -g yarn
}

create_user_and_sync() {
  log "Preparing the application folder"
  id "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  mkdir -p "$APP_DIR" "$APP_DIR/.home" "$WEB_ROOT" "$BACKUP_DIR"
  if [[ "$SRC_DIR" != "$APP_DIR" ]]; then
    rsync -a --delete \
      --exclude '.git' --exclude 'node_modules' --exclude 'build' --exclude '.venv' --exclude '__pycache__' \
      --exclude '.env' --exclude '.home' --exclude '.setup_done' \
      "$SRC_DIR"/ "$APP_DIR"/
  fi
  chown -R "$SERVICE_USER":"$SERVICE_USER" "$APP_DIR"
}

setup_backend() {
  log "Setting up the backend"
  local be="$APP_DIR/backend" envf="$APP_DIR/backend/.env"
  runuser -u "$SERVICE_USER" -- python3 -m venv "$be/.venv"
  runuser -u "$SERVICE_USER" -- "$be/.venv/bin/pip" install --quiet --upgrade pip wheel
  runuser -u "$SERVICE_USER" -- "$be/.venv/bin/pip" install --quiet -r "$be/requirements.txt"

  touch "$envf"; chown "$SERVICE_USER":"$SERVICE_USER" "$envf"; chmod 600 "$envf"
  has_env "$envf" MONGO_URL     || set_env "$envf" MONGO_URL "mongodb://127.0.0.1:27017"
  has_env "$envf" DB_NAME       || set_env "$envf" DB_NAME "$DB_NAME"
  has_env "$envf" JWT_SECRET    || set_env "$envf" JWT_SECRET "$(rand_secret)"
  has_env "$envf" SEED_USER_PASSWORD || set_env "$envf" SEED_USER_PASSWORD "$(rand_pass)"
  has_env "$envf" REMINDER_SWEEP_MINUTES || set_env "$envf" REMINDER_SWEEP_MINUTES "15"
  [[ -n "${EMERGENT_LLM_KEY:-}" ]] && set_env "$envf" EMERGENT_LLM_KEY "$EMERGENT_LLM_KEY"
  # These two depend on the address/protocol chosen on every run
  set_env "$envf" FRONTEND_URL "$BASE_URL"
  if [[ "$ENABLE_HTTPS" == "yes" ]]; then set_env "$envf" COOKIE_SECURE "true"; else set_env "$envf" COOKIE_SECURE "false"; fi
  chown "$SERVICE_USER":"$SERVICE_USER" "$envf"
}

build_frontend() {
  if (( ! DO_BUILD )); then log "Skipping frontend build (--no-build)"; return 0; fi
  log "Building the frontend (this takes a few minutes)"
  local fe="$APP_DIR/frontend"
  printf "REACT_APP_BACKEND_URL=%s\n" "$BASE_URL" > "$fe/.env"
  chown "$SERVICE_USER":"$SERVICE_USER" "$fe/.env"
  local run=(runuser -u "$SERVICE_USER" -- env HOME="$APP_DIR/.home" CI=false NODE_OPTIONS=--max-old-space-size=2048)
  if [[ -f "$fe/yarn.lock" ]]; then
    (cd "$fe" && "${run[@]}" yarn install --network-timeout 600000 && "${run[@]}" yarn build)
  else
    (cd "$fe" && { "${run[@]}" npm ci --legacy-peer-deps || "${run[@]}" npm install --legacy-peer-deps; } && "${run[@]}" npm run build)
  fi
  [[ -f "$fe/build/index.html" ]] || die "Frontend build failed (no build/index.html)."
  rsync -a --delete "$fe/build"/ "$WEB_ROOT"/
  chmod -R a+rX "$WEB_ROOT"
}

setup_service() {
  log "Installing the backend service"
  render_service > /etc/systemd/system/irm.service
  systemctl daemon-reload
  systemctl enable irm >/dev/null
  systemctl restart irm
}

setup_first_admin() {
  [[ -f "$APP_DIR/.setup_done" ]] && { info "First admin already created on a previous run - skipping"; return 0; }
  log "Creating base departments and the first Super Admin"
  local envf="$APP_DIR/backend/.env"
  set_env "$envf" ADMIN_NAME "$ADMIN_NAME"
  set_env "$envf" ADMIN_EMAIL "$ADMIN_EMAIL"
  set_env "$envf" ADMIN_PASSWORD "$ADMIN_PASSWORD"
  chown "$SERVICE_USER":"$SERVICE_USER" "$envf"
  (cd "$APP_DIR/backend" && runuser -u "$SERVICE_USER" -- "$APP_DIR/backend/.venv/bin/python" create_super_admin.py)
  unset_env "$envf" ADMIN_PASSWORD          # do not leave the password sitting in a file
  chown "$SERVICE_USER":"$SERVICE_USER" "$envf"
  touch "$APP_DIR/.setup_done"
}

setup_nginx() {
  log "Configuring Nginx"
  if [[ "$ENABLE_HTTPS" == "yes" && ! -f /etc/ssl/irm/irm.crt ]]; then
    mkdir -p /etc/ssl/irm
    local san; if is_ip "$SERVER_NAME"; then san="IP:${SERVER_NAME}"; else san="DNS:${SERVER_NAME}"; fi
    openssl req -x509 -nodes -newkey rsa:2048 -days 825 -subj "/CN=${SERVER_NAME}" -addext "subjectAltName=${san}" \
      -keyout /etc/ssl/irm/irm.key -out /etc/ssl/irm/irm.crt 2>/dev/null
    chmod 600 /etc/ssl/irm/irm.key
    info "Created a self-signed certificate (browsers will show a one-time warning)."
  fi
  render_nginx "$SERVER_NAME" "$ENABLE_HTTPS" > /etc/nginx/sites-available/irm
  ln -sf /etc/nginx/sites-available/irm /etc/nginx/sites-enabled/irm
  rm -f /etc/nginx/sites-enabled/default
  nginx -t
  systemctl enable nginx >/dev/null
  systemctl reload nginx || systemctl restart nginx
}

setup_firewall_and_backup() {
  log "Firewall and nightly backup"
  ufw allow OpenSSH >/dev/null
  ufw allow 80/tcp >/dev/null
  ufw allow 443/tcp >/dev/null
  ufw --force enable >/dev/null
  info "Firewall on: SSH, 80, 443 open. MongoDB is reachable only from this machine."

  cat > /etc/cron.d/irm-backup <<EOF
# IRM: nightly MongoDB dump at 02:00, keep 14 days
0 2 * * * root mongodump --quiet --db ${DB_NAME} --archive=${BACKUP_DIR}/irm-\$(date +\\%F).gz --gzip && find ${BACKUP_DIR} -name 'irm-*.gz' -mtime +14 -delete
EOF
  chmod 644 /etc/cron.d/irm-backup
  info "Backups go to ${BACKUP_DIR} (copy them off this VM regularly)."
}

health_check() {
  log "Checking that everything is up"
  local ok=0
  for _ in $(seq 1 30); do
    if curl -fs "http://127.0.0.1:${BACKEND_PORT}/docs" >/dev/null 2>&1; then ok=1; break; fi
    sleep 1
  done
  (( ok )) || { journalctl -u irm -n 30 --no-pager || true; die "Backend did not start. See the log above (also: journalctl -u irm -f)."; }
  curl -fsk "${BASE_URL}/" >/dev/null 2>&1 && info "Website: OK" || warn "Website did not answer on ${BASE_URL} from this machine - check Nginx (sudo nginx -t)."
  info "Backend: OK"
}

summary() {
  cat <<EOF

================  IRM is installed  ================
  Open:        ${BASE_URL}
  Sign in:     the Super Admin email you entered
  Backend:     sudo systemctl status irm      |  logs: sudo journalctl -u irm -f
  Update:      git pull && sudo bash deploy/setup.sh
  Backups:     ${BACKUP_DIR}  (nightly 02:00, 14 days)
  Settings:    ${APP_DIR}/backend/.env   (keep private)

  Next steps in the app:  Organization > Departments, Products, Users and Roles (or Bulk Import).
$( [[ "$ENABLE_HTTPS" == "yes" ]] && echo "  HTTPS note:  the certificate is self-signed - accept the browser warning once, or install /etc/ssl/irm/irm.crt on each PC." )
$( [[ "$ENABLE_HTTPS" != "yes" ]] && echo "  HTTP note:   passwords travel unencrypted on your network. Re-run with --https to fix that." )
  File attachments need internet access and EMERGENT_LLM_KEY in the .env file (see README).
EOF
  printf '\n'
}

main() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --server) SERVER_NAME="${2:-}"; shift ;;
      --https)  ENABLE_HTTPS=yes ;;
      --http)   ENABLE_HTTPS=no ;;
      --no-build) DO_BUILD=0 ;;
      --yes|-y) ASSUME_YES=1 ;;
      -h|--help) usage; exit 0 ;;
      *) die "Unknown option: $1 (try --help)" ;;
    esac
    shift
  done
  preflight
  gather_config
  install_packages
  install_mongo
  install_node
  create_user_and_sync
  setup_backend
  build_frontend
  setup_service
  setup_first_admin
  setup_nginx
  setup_firewall_and_backup
  health_check
  summary
}

# Allow tests to load the functions without running the installer.
if [[ "${IRM_SOURCE_ONLY:-0}" != "1" ]]; then main "$@"; fi
