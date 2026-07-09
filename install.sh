#!/usr/bin/env bash
set -Eeuo pipefail

VERSION="v0.9.4"
TARGET=""
INSTALL_DIR=""
BIND_HOST=""
PORT="8080"
ENV_MODE=""
COOKIE_SECURE=""
ADMIN_EMAIL="${CVD_ADMIN_EMAIL:-}"
ADMIN_PASSWORD="${CVD_ADMIN_PASSWORD:-}"
LM_URL="${LM_STUDIO_API_URL:-http://127.0.0.1:1234/v1/chat/completions}"
LM_MODEL="${LM_STUDIO_MODEL:-medgemma-27b-text-it-mlx}"
DOMAIN=""
ENABLE_SERVICE=1
INSTALL_PACKAGES=1
UNATTENDED=0
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ -d "$SOURCE_DIR/cvd_web" ]] || { printf 'install.sh must be located in the CVD Web release directory\n' >&2; exit 1; }

usage() {
  cat <<'EOF'
CVD Web beta installer

Usage:
  ./install.sh --target local|vps|wsl2 [options]

Targets:
  local   macOS or Linux workstation, available in the home network
  vps     Debian/Ubuntu VPS with systemd; run as root
  wsl2    Ubuntu/Debian under WSL2

Options:
  --install-dir PATH       Override installation directory
  --bind HOST              Bind address (defaults: local/wsl2 0.0.0.0, vps 127.0.0.1)
  --port PORT              HTTP port, default 8080
  --env MODE               CVD_ENV: development, controlled, or production
  --cookie-secure 0|1      Set Secure flag for session cookies; use 1 behind HTTPS
  --admin-email EMAIL      Initial administrator email
  --admin-password PASS    Initial password, minimum 15 characters
  --lm-url URL             LM Studio /v1/chat/completions endpoint
  --lm-model MODEL         LM Studio model identifier
  --domain DOMAIN          Configure nginx virtual host on VPS
  --no-service             Install files only; do not enable/start a service
  --skip-packages          Do not install missing OS packages
  --unattended             Do not prompt; generate missing credentials
  -h, --help               Show this help

Examples:
  ./install.sh --target local
  sudo ./install.sh --target vps --domain cvd.example.com --lm-url http://10.8.0.2:1234/v1/chat/completions
  ./install.sh --target wsl2 --lm-url http://127.0.0.1:1234/v1/chat/completions
EOF
}

log() { printf '\n[CVD] %s\n' "$*"; }
fail() { printf '\n[CVD] ERROR: %s\n' "$*" >&2; exit 1; }
command_exists() { command -v "$1" >/dev/null 2>&1; }

while (($#)); do
  case "$1" in
    --target) TARGET="${2:-}"; shift 2 ;;
    --install-dir) INSTALL_DIR="${2:-}"; shift 2 ;;
    --bind) BIND_HOST="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --env) ENV_MODE="${2:-}"; shift 2 ;;
    --cookie-secure) COOKIE_SECURE="${2:-}"; shift 2 ;;
    --admin-email) ADMIN_EMAIL="${2:-}"; shift 2 ;;
    --admin-password) ADMIN_PASSWORD="${2:-}"; shift 2 ;;
    --lm-url) LM_URL="${2:-}"; shift 2 ;;
    --lm-model) LM_MODEL="${2:-}"; shift 2 ;;
    --domain) DOMAIN="${2:-}"; shift 2 ;;
    --no-service) ENABLE_SERVICE=0; shift ;;
    --skip-packages) INSTALL_PACKAGES=0; shift ;;
    --unattended) UNATTENDED=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown option: $1" ;;
  esac
done

if [[ -z "$TARGET" ]]; then
  if [[ -r /proc/version ]] && grep -qi microsoft /proc/version; then
    TARGET="wsl2"
  else
    TARGET="local"
  fi
fi
[[ "$TARGET" =~ ^(local|vps|wsl2)$ ]] || fail "Target must be local, vps, or wsl2"
[[ "$PORT" =~ ^[0-9]+$ ]] && ((PORT >= 1 && PORT <= 65535)) || fail "Port must be between 1 and 65535"
if [[ -n "$ENV_MODE" ]]; then
  [[ "$ENV_MODE" =~ ^(development|controlled|production)$ ]] || fail "--env must be development, controlled, or production"
fi
if [[ -n "$COOKIE_SECURE" ]]; then
  [[ "$COOKIE_SECURE" =~ ^[01]$ ]] || fail "--cookie-secure must be 0 or 1"
fi
[[ "$LM_URL" =~ ^https?://[^[:space:]]+$ ]] || fail "LM Studio URL must be an http(s) URL without spaces"
[[ "$LM_MODEL" != *$'\n'* && -n "$LM_MODEL" ]] || fail "LM Studio model is invalid"
[[ "$DOMAIN" != *$'\n'* && "$DOMAIN" != *' '* ]] || fail "Domain is invalid"

if [[ "$TARGET" == "vps" && "$EUID" -ne 0 ]]; then
  fail "VPS installation must be run as root: sudo ./install.sh --target vps ..."
fi
if [[ "$TARGET" == "wsl2" ]]; then
  [[ -r /proc/version ]] && grep -qi microsoft /proc/version || fail "WSL2 target selected outside WSL2"
fi

if [[ -z "$INSTALL_DIR" ]]; then
  if [[ "$TARGET" == "vps" ]]; then
    INSTALL_DIR="/opt/cvd-web"
  else
    INSTALL_DIR="${HOME}/.local/share/cvd-web"
  fi
fi
if [[ -z "$BIND_HOST" ]]; then
  [[ "$TARGET" == "vps" ]] && BIND_HOST="127.0.0.1" || BIND_HOST="0.0.0.0"
fi
if [[ -z "$ENV_MODE" ]]; then
  [[ "$TARGET" == "vps" ]] && ENV_MODE="controlled" || ENV_MODE="development"
fi
if [[ -z "$COOKIE_SECURE" ]]; then
  if [[ "$TARGET" == "vps" && "$ENV_MODE" == "production" ]]; then
    COOKIE_SECURE="1"
  else
    COOKIE_SECURE="0"
  fi
fi

install_apt_packages() {
  local packages=(python3 ca-certificates)
  [[ "$TARGET" == "vps" && -n "$DOMAIN" ]] && packages+=(nginx)
  if ! command_exists apt-get; then
    return
  fi
  if [[ "$INSTALL_PACKAGES" -eq 1 ]]; then
    if [[ "$EUID" -eq 0 ]]; then
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
    elif command_exists sudo; then
      sudo apt-get update
      sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${packages[@]}"
    fi
  fi
}

if ! command_exists python3; then
  install_apt_packages
fi
command_exists python3 || fail "Python 3 is required"
python3 - <<'PY' || fail "Python 3.11 or newer is required"
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

if [[ -z "$ADMIN_EMAIL" && "$UNATTENDED" -eq 0 ]]; then
  read -r -p "Administrator email [admin@cvd.local]: " ADMIN_EMAIL
fi
ADMIN_EMAIL="${ADMIN_EMAIL:-admin@cvd.local}"
[[ "$ADMIN_EMAIL" =~ ^[^[:space:]@]+@[^[:space:]@]+$ ]] || fail "Administrator email is invalid"

GENERATED_PASSWORD=0
if [[ -z "$ADMIN_PASSWORD" && "$UNATTENDED" -eq 0 ]]; then
  read -r -s -p "Administrator password (minimum 15 characters, empty = generate): " ADMIN_PASSWORD
  printf '\n'
fi
if [[ -z "$ADMIN_PASSWORD" ]]; then
  ADMIN_PASSWORD="$(python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(24))
PY
)"
  GENERATED_PASSWORD=1
fi
(( ${#ADMIN_PASSWORD} >= 15 )) || fail "Administrator password must contain at least 15 characters"
for value in "$ADMIN_EMAIL" "$ADMIN_PASSWORD" "$LM_URL" "$LM_MODEL"; do
  [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] || fail "Configuration values must not contain newlines"
  [[ "$value" =~ ^[A-Za-z0-9@%_+.,:/?=~!#^-]+$ ]] || fail "Configuration values contain unsupported shell characters"
done

if [[ "$TARGET" == "vps" ]]; then
  DATA_DIR="/var/lib/cvd-web"
  BACKUP_DIR="/var/backups/cvd-web"
  ENV_DIR="/etc/cvd-web"
  ENV_FILE="${ENV_DIR}/cvd-web.env"
  SERVICE_USER="cvd-web"
else
  DATA_DIR="${INSTALL_DIR}/data"
  BACKUP_DIR="${INSTALL_DIR}/backups"
  ENV_DIR="${INSTALL_DIR}/config"
  ENV_FILE="${ENV_DIR}/cvd-web.env"
  SERVICE_USER="$(id -un)"
fi

EXISTING_DB=0
[[ -f "$DATA_DIR/cvd.sqlite3" ]] && EXISTING_DB=1

log "Installing CVD Web ${VERSION} for ${TARGET}"

if [[ "$TARGET" == "vps" ]]; then
  if ! id "$SERVICE_USER" >/dev/null 2>&1; then
    useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  fi
fi

mkdir -p "$INSTALL_DIR" "$DATA_DIR" "$BACKUP_DIR" "$ENV_DIR" "$INSTALL_DIR/bin"

copy_source() {
  local archive
  archive="$(mktemp)"
  tar -C "$SOURCE_DIR" \
    --exclude='.git' --exclude='.env' --exclude='data' --exclude='backups' \
    --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
    -cf "$archive" .
  tar -C "$INSTALL_DIR" -xf "$archive"
  rm -f "$archive"
}
copy_source

cat >"$ENV_FILE" <<EOF
CVD_HOST=${BIND_HOST}
CVD_PORT=${PORT}
CVD_ENV=${ENV_MODE}
CVD_DB_PATH=${DATA_DIR}/cvd.sqlite3
CVD_COOKIE_SECURE=${COOKIE_SECURE}
CVD_SESSION_DAYS=7
CVD_ADMIN_EMAIL=${ADMIN_EMAIL}
CVD_ADMIN_PASSWORD=${ADMIN_PASSWORD}
LM_STUDIO_API_URL=${LM_URL}
LM_STUDIO_MODEL=${LM_MODEL}
LM_STUDIO_TIMEOUT_SECONDS=300
LM_STUDIO_MAX_TOKENS=1536
LM_STUDIO_TEMPERATURE=0.1
CVD_MAX_REQUEST_BYTES=2097152
CVD_BACKUP_DIR=${BACKUP_DIR}
EOF
chmod 600 "$ENV_FILE"

cat >"$INSTALL_DIR/bin/cvd-web" <<EOF
#!/usr/bin/env bash
set -a
. "${ENV_FILE}"
set +a
cd "${INSTALL_DIR}"
exec "$(command -v python3)" -m cvd_web
EOF
chmod 755 "$INSTALL_DIR/bin/cvd-web"

if [[ "$TARGET" == "vps" ]]; then
  chown -R root:root "$INSTALL_DIR"
  chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR" "$BACKUP_DIR"
  chown root:"$SERVICE_USER" "$ENV_FILE"
  chmod 640 "$ENV_FILE"
fi

install_systemd_service() {
  local service_path="$1"
  local systemctl_cmd=("${@:2}")
  cat >"$service_path" <<EOF
[Unit]
Description=CVD Web beta
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}
ExecStart=${INSTALL_DIR}/bin/cvd-web
Restart=on-failure
RestartSec=5
TimeoutStopSec=30

[Install]
WantedBy=default.target
EOF
  "${systemctl_cmd[@]}" daemon-reload
  "${systemctl_cmd[@]}" enable --now cvd-web.service
}

if [[ "$ENABLE_SERVICE" -eq 1 ]]; then
  if [[ "$TARGET" == "vps" ]]; then
    cat >"/etc/systemd/system/cvd-web.service" <<EOF
[Unit]
Description=CVD Web beta
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=$(command -v python3) -m cvd_web
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=${DATA_DIR} ${BACKUP_DIR}

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable --now cvd-web.service
  elif [[ "$(uname -s)" == "Darwin" ]]; then
    PLIST="$HOME/Library/LaunchAgents/com.cvd.web.plist"
    mkdir -p "$(dirname "$PLIST")" "$INSTALL_DIR/logs"
    cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.cvd.web</string>
  <key>ProgramArguments</key><array><string>${INSTALL_DIR}/bin/cvd-web</string></array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${INSTALL_DIR}/logs/cvd-web.log</string>
  <key>StandardErrorPath</key><string>${INSTALL_DIR}/logs/cvd-web-error.log</string>
</dict></plist>
EOF
    launchctl bootout "gui/${UID}" "$PLIST" >/dev/null 2>&1 || true
    launchctl bootstrap "gui/${UID}" "$PLIST"
  elif command_exists systemctl && [[ "$(ps -p 1 -o comm= 2>/dev/null || true)" == "systemd" ]]; then
    USER_SERVICE_DIR="$HOME/.config/systemd/user"
    mkdir -p "$USER_SERVICE_DIR"
    install_systemd_service "$USER_SERVICE_DIR/cvd-web.service" systemctl --user
  else
    nohup "$INSTALL_DIR/bin/cvd-web" >"$INSTALL_DIR/cvd-web.log" 2>&1 &
    printf '%s\n' "$!" >"$INSTALL_DIR/cvd-web.pid"
  fi
fi

if [[ "$TARGET" == "vps" && -n "$DOMAIN" ]]; then
  install_apt_packages
  command_exists nginx || fail "nginx is required when --domain is used"
  cat >"/etc/nginx/sites-available/cvd-web.conf" <<EOF
server {
    listen 80;
    server_name ${DOMAIN};
    client_max_body_size 20m;
    location / {
        proxy_pass http://127.0.0.1:${PORT};
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF
  ln -sfn /etc/nginx/sites-available/cvd-web.conf /etc/nginx/sites-enabled/cvd-web.conf
  nginx -t
  systemctl reload nginx
fi

lan_ip() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true
  else
    hostname -I 2>/dev/null | awk '{print $1}'
  fi
}
LAN_IP="$(lan_ip)"

log "Installation complete"
printf 'Target:        %s\n' "$TARGET"
printf 'CVD_ENV:       %s\n' "$ENV_MODE"
printf 'Install path:  %s\n' "$INSTALL_DIR"
printf 'Configuration: %s\n' "$ENV_FILE"
printf 'Local URL:     http://127.0.0.1:%s\n' "$PORT"
if [[ "$BIND_HOST" == "0.0.0.0" && -n "$LAN_IP" ]]; then
  printf 'LAN URL:       http://%s:%s\n' "$LAN_IP" "$PORT"
fi
if [[ "$TARGET" == "vps" && -n "$DOMAIN" ]]; then
  printf 'Public URL:    http://%s\n' "$DOMAIN"
  printf 'TLS:           configure HTTPS before using real accounts or medical data\n'
fi
printf 'Admin email:   %s\n' "$ADMIN_EMAIL"
if [[ "$GENERATED_PASSWORD" -eq 1 ]]; then
  if [[ "$EXISTING_DB" -eq 0 ]]; then
    printf 'Admin password: %s\n' "$ADMIN_PASSWORD"
    printf 'Store this password now; it is shown only by the installer.\n'
  else
    printf 'Admin password: unchanged (existing database preserved)\n'
  fi
fi
if [[ "$ENABLE_SERVICE" -eq 0 ]]; then
  printf 'Start command: %s/bin/cvd-web\n' "$INSTALL_DIR"
fi
if [[ "$TARGET" == "wsl2" && -n "$LAN_IP" ]]; then
  cat <<EOF

From Windows on the same machine, open:
  http://localhost:${PORT}

For access from other home-network devices, run PowerShell as Administrator:
  netsh interface portproxy add v4tov4 listenport=${PORT} listenaddress=0.0.0.0 connectport=${PORT} connectaddress=${LAN_IP}
  New-NetFirewallRule -DisplayName "CVD Web ${PORT}" -Direction Inbound -Action Allow -Protocol TCP -LocalPort ${PORT}
EOF
fi
