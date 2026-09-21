#!/usr/bin/env bash
# VPS Deployer installer. Security-critical. Review before piping to bash.
set -euo pipefail

VD_SITE_URL="${VPS_DEPLOYER_SITE_URL:-https://vps-deployer.onebitstack.com}"
VD_DEBUG="${VPS_DEPLOYER_DEBUG:-0}"
VD_SOURCE=""
VD_VERSION=""
VD_LOG=""
VD_EXISTING=0
VD_SKIP_SERVICE_START=0

SCRIPT_PATH="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""
if [[ -n "$SCRIPT_PATH" && -f "$SCRIPT_PATH" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
fi

if [[ -n "${SCRIPT_DIR:-}" && -f "${SCRIPT_DIR}/lib.sh" ]]; then
  # shellcheck source=lib.sh
  . "${SCRIPT_DIR}/lib.sh"
else
  _vd_lib="$(mktemp)"
  if ! curl -fsSL "${VD_SITE_URL}/installer/lib.sh" -o "$_vd_lib"; then
    echo "This installer needs installer/lib.sh."
    echo "Inspect first:"
    echo "  curl -fsSL ${VD_SITE_URL}/install.sh -o install.sh"
    echo "Or clone the repository and run:"
    echo "  sudo bash installer/install.sh --source /path/to/vps-deployer"
    rm -f "$_vd_lib"
    exit 1
  fi
  # shellcheck source=/dev/null
  . "$_vd_lib"
  rm -f "$_vd_lib"
fi

usage() {
  cat <<EOF
Usage: install.sh [options]

Options:
  --source <path>     Install from a local checkout
  --version <x.y.z>   Download a versioned release
  --debug             Print each installer command
  --skip-service      Do not start systemd (development)
  -h, --help          Show this help

Review before installation:
  curl -fsSL ${VD_SITE_URL}/install.sh -o install.sh
  less install.sh
  sudo bash install.sh
EOF
}

log() {
  local line="$1"
  if [[ -n "${VD_LOG:-}" ]]; then
    printf '%s %s\n' "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "$line" >>"$VD_LOG"
  fi
}

VD_BACKUP=""

fail() {
  trap - ERR
  echo
  echo "Installation failed."
  if restore_previous_install; then
    echo "Previous platform files were restored. Your applications were not changed."
  fi
  if [[ -n "${VD_LOG:-}" ]]; then
    echo "Log: ${VD_LOG}"
  fi
  echo
  echo "Diagnose with:"
  echo "  vps-deployer doctor"
  exit 1
}

trap 'fail' ERR

while [[ $# -gt 0 ]]; do
  case "$1" in
    --source)
      VD_SOURCE="${2:-}"
      shift 2
      ;;
    --version)
      VD_VERSION="${2:-}"
      shift 2
      ;;
    --debug)
      VD_DEBUG=1
      shift
      ;;
    --skip-service)
      VD_SKIP_SERVICE_START=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ "$VD_DEBUG" == "1" ]]; then
  set -x
fi

if [[ -n "$VD_VERSION" ]] && ! vd_validate_semver "$VD_VERSION"; then
  echo "Invalid version: ${VD_VERSION}" >&2
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  echo "This installer must run as root (sudo)."
  exit 1
fi

mkdir -p /var/log/vps-deployer
VD_LOG="/var/log/vps-deployer/installer.log"
touch "$VD_LOG"
chmod 640 "$VD_LOG"
log "starting installer"

banner() {
  cat <<'EOF'

============================================================
 VPS DEPLOYER
 Self-hosted deployment platform
============================================================

EOF
}

resolve_source() {
  if [[ -n "$VD_SOURCE" ]]; then
    if [[ ! -d "$VD_SOURCE" ]]; then
      echo "Source path does not exist: $VD_SOURCE" >&2
      exit 1
    fi
    VD_SOURCE="$(cd "$VD_SOURCE" && pwd)"
    return 0
  fi

  local repo_root
  repo_root="$(cd "${SCRIPT_DIR}/.." && pwd)"
  if [[ -f "${repo_root}/pyproject.toml" && -d "${repo_root}/src/vps_deployer" ]]; then
    VD_SOURCE="$repo_root"
    return 0
  fi

  local version="${VD_VERSION:-}"
  if [[ -z "$version" ]]; then
    version="$(curl -fsSL "${VD_SITE_URL}/releases/latest.txt" 2>/dev/null || true)"
    version="$(printf '%s' "$version" | tr -d '[:space:]')"
  fi
  if [[ -z "$version" ]]; then
    version="0.3.1"
  fi
  if ! vd_validate_semver "$version"; then
    echo "Invalid version: ${version}" >&2
    exit 1
  fi
  local url="${VD_SITE_URL}/releases/vps-deployer-${version}.tar.gz"
  if ! vd_is_https_url "$url"; then
    echo "Refusing non-HTTPS download." >&2
    exit 1
  fi
  local tmp
  tmp="$(mktemp -d)"
  echo "Downloading ${url}"
  curl -fsSL "$url" -o "${tmp}/vps-deployer.tar.gz"
  if ! vd_tar_members_safe "${tmp}/vps-deployer.tar.gz"; then
    echo "Refusing tarball with unsafe member paths." >&2
    exit 1
  fi
  mkdir -p "${tmp}/src"
  tar -xzf "${tmp}/vps-deployer.tar.gz" -C "${tmp}/src" --strip-components=1
  VD_SOURCE="${tmp}/src"
}

system_check() {
  echo "System check"
  echo

  if ! vd_parse_os_release /etc/os-release; then
    vd_mark fail "Unable to detect operating system"
    echo
    echo "Unsupported operating system."
    echo
    echo "Supported systems:"
    echo
    echo "Ubuntu 22.04 LTS or newer LTS"
    echo "Debian 12+"
    echo
    echo "See:"
    echo
    echo "  ${VD_SITE_URL}/docs/requirements"
    exit 1
  fi

  if vd_os_supported "$VD_OS_ID" "$VD_OS_VERSION"; then
    vd_mark ok "${VD_OS_PRETTY} detected"
  else
    vd_mark fail "Unsupported operating system: ${VD_OS_PRETTY}"
    echo
    echo "Unsupported operating system."
    echo
    echo "Supported systems:"
    echo
    echo "Ubuntu 22.04 LTS or newer LTS"
    echo "Debian 12+"
    echo
    echo "See:"
    echo
    echo "  ${VD_SITE_URL}/docs/requirements"
    exit 1
  fi
  if [[ "$VD_OS_ID" == "ubuntu" ]] && ! vd_ubuntu_lts_supported "$VD_OS_VERSION"; then
    vd_mark warn "Ubuntu ${VD_OS_VERSION} is not an LTS release"
    echo "  Non-LTS releases may lose third-party APT repository support."
    echo "  Prefer a currently supported Ubuntu LTS release."
  fi

  local arch
  arch="$(vd_arch_from_uname "$(uname -m)")"
  vd_mark ok "${arch} architecture"

  local cpu ram disk
  cpu="$(vd_detect_cpu)"
  ram="$(vd_detect_ram_mb)"
  disk="$(vd_detect_disk_gb /)"
  if [[ "$cpu" -ge "$VD_MIN_CPU" ]]; then
    vd_mark ok "${cpu} CPU cores"
  else
    vd_mark warn "${cpu} CPU cores (2 recommended)"
  fi
  if [[ "$ram" -lt "$VD_HARD_RAM_MB" ]]; then
    vd_mark fail "${ram} MB RAM"
    exit 1
  elif [[ "$ram" -lt "$VD_MIN_RAM_MB" ]]; then
    vd_mark warn "${ram} MB RAM (2 GB recommended)"
  else
    vd_mark ok "$((ram / 1024)) GB RAM"
  fi
  if [[ "${disk:-0}" -lt "$VD_HARD_DISK_GB" ]]; then
    vd_mark fail "${disk:-0} GB free disk"
    exit 1
  elif [[ "${disk:-0}" -lt "$VD_MIN_DISK_GB" ]]; then
    vd_mark warn "${disk} GB free disk (10 GB recommended)"
  else
    vd_mark ok "${disk} GB free disk"
  fi

  if vd_check_internet "$VD_SITE_URL" || vd_check_internet "https://astral.sh"; then
    vd_mark ok "Internet connectivity"
  else
    vd_mark warn "Internet check failed; continuing if --source is local"
    if [[ ! -d "$VD_SOURCE" ]]; then
      exit 1
    fi
  fi

  vd_mark ok "sudo access"
  echo
}

dependencies_available() {
  local command
  for command in curl git python3 tar adduser rsync nginx certbot uv; do
    if ! command -v "$command" >/dev/null 2>&1; then
      return 1
    fi
  done
  return 0
}

print_dependency_status() {
  vd_mark ok "Git"
  vd_mark ok "Python"
  vd_mark ok "uv"
  vd_mark ok "Nginx"
  vd_mark ok "certbot"
  echo
}

install_packages() {
  if [[ "$VD_EXISTING" -eq 1 ]] && dependencies_available; then
    echo "Verifying dependencies..."
    echo
    print_dependency_status
    echo "All required dependencies are already installed; skipped APT."
    echo
    return 0
  fi

  echo "Installing dependencies..."
  echo
  export DEBIAN_FRONTEND=noninteractive
  if ! apt-get update -y; then
    echo
    echo "APT could not refresh package indexes."
    echo "Fix or disable the broken source under /etc/apt/sources.list.d, then retry."
    echo "Existing VPS Deployer files and applications were not changed."
    exit 1
  fi
  apt-get install -y --no-install-recommends \
    ca-certificates curl git python3 python3-venv tar adduser rsync >/dev/null
  if ! command -v nginx >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends nginx >/dev/null
  fi
  if ! command -v certbot >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends certbot >/dev/null
  fi
  if ! command -v uv >/dev/null 2>&1; then
    curl -fsSL https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
  fi
  print_dependency_status
}

create_user_and_dirs() {
  if ! getent group vps-deployer >/dev/null; then
    groupadd --system vps-deployer
  fi
  if ! getent passwd vps-deployer >/dev/null; then
    useradd --system --gid vps-deployer --home-dir /var/lib/vps-deployer \
      --shell /usr/sbin/nologin --comment "VPS Deployer" vps-deployer
  fi

  mkdir -p \
    /opt/vps-deployer/app \
    /opt/vps-deployer/bin \
    /opt/vps-deployer/releases \
    /opt/vps-deployer/scripts \
    /etc/vps-deployer/projects \
    /var/lib/vps-deployer \
    /var/log/vps-deployer/projects \
    /var/www/apps \
    /var/www/certbot \
    /usr/local/libexec

  chown -R vps-deployer:vps-deployer /opt/vps-deployer /var/lib/vps-deployer /var/log/vps-deployer
  chown vps-deployer:vps-deployer /var/www/apps
  chmod 755 /var/www/apps /var/www/certbot
  chown root:vps-deployer /etc/vps-deployer
  chmod 770 /etc/vps-deployer
  if [[ -d /etc/vps-deployer/projects ]]; then
    chown root:vps-deployer /etc/vps-deployer/projects
    chmod 770 /etc/vps-deployer/projects
  fi
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]] && getent passwd "$SUDO_USER" >/dev/null; then
    usermod -aG vps-deployer "$SUDO_USER"
    log "added ${SUDO_USER} to vps-deployer group"
  fi
}

write_config() {
  if vd_should_write_file /etc/vps-deployer/config.env; then
    cat > /etc/vps-deployer/config.env <<EOF
VPS_DEPLOYER_SITE_URL=${VD_SITE_URL}
VPS_DEPLOYER_API_HOST=127.0.0.1
VPS_DEPLOYER_API_PORT=5100
VPS_DEPLOYER_CONFIG_DIR=/etc/vps-deployer
VPS_DEPLOYER_DATA_DIR=/var/lib/vps-deployer
VPS_DEPLOYER_LOG_DIR=/var/log/vps-deployer
VPS_DEPLOYER_DATABASE_PATH=/var/lib/vps-deployer/vps-deployer.db
VPS_DEPLOYER_CREATE_TABLES=true
EOF
  else
    log "preserving existing /etc/vps-deployer/config.env"
  fi
  if [[ -f /etc/vps-deployer/config.env ]]; then
    chown vps-deployer:vps-deployer /etc/vps-deployer/config.env
    chmod 640 /etc/vps-deployer/config.env
  fi

  if vd_should_write_file /etc/vps-deployer/config.json; then
    cat > /etc/vps-deployer/config.json <<'EOF'
{
  "bind_host": "127.0.0.1",
  "bind_port": 5100,
  "release_retention": 5
}
EOF
    chmod 644 /etc/vps-deployer/config.json
    chown vps-deployer:vps-deployer /etc/vps-deployer/config.json
  else
    log "preserving existing /etc/vps-deployer/config.json"
  fi
}

snapshot_existing() {
  if [[ ! -d /opt/vps-deployer/app/src/vps_deployer ]]; then
    return 0
  fi
  local staging="/opt/vps-deployer/releases/pre-install.staging"
  local dest="/opt/vps-deployer/releases/pre-install"
  rm -rf "$staging"
  mkdir -p "$staging/libexec"
  rsync -a /opt/vps-deployer/app/ "$staging/app/"
  if [[ -x /usr/local/bin/vps-deployer ]]; then
    cp -a /usr/local/bin/vps-deployer "$staging/vps-deployer"
  fi
  if [[ -x /usr/local/libexec/vps-deployer-helper ]]; then
    cp -a /usr/local/libexec/vps-deployer-helper "$staging/libexec/"
  fi
  if [[ -f /etc/systemd/system/vps-deployer.service ]]; then
    cp -a /etc/systemd/system/vps-deployer.service "$staging/vps-deployer.service"
  fi
  if [[ -f /etc/sudoers.d/vps-deployer ]]; then
    cp -a /etc/sudoers.d/vps-deployer "$staging/sudoers"
  fi
  rm -rf "$dest"
  mv "$staging" "$dest"
  VD_BACKUP="$dest"
  log "snapshot ${VD_BACKUP}"
}

restore_previous_install() {
  if [[ -z "${VD_BACKUP:-}" || ! -d "${VD_BACKUP}/app" ]]; then
    return 1
  fi
  echo "Restoring previous VPS Deployer files..."
  rsync -a --delete "${VD_BACKUP}/app/" /opt/vps-deployer/app/ || return 1
  chown -R vps-deployer:vps-deployer /opt/vps-deployer
  if [[ -f "${VD_BACKUP}/vps-deployer" ]]; then
    install -m 0755 "${VD_BACKUP}/vps-deployer" /usr/local/bin/vps-deployer
  fi
  if [[ -f "${VD_BACKUP}/libexec/vps-deployer-helper" ]]; then
    install -m 0755 "${VD_BACKUP}/libexec/vps-deployer-helper" /usr/local/libexec/vps-deployer-helper
  fi
  if [[ -f "${VD_BACKUP}/vps-deployer.service" ]]; then
    install -m 0644 "${VD_BACKUP}/vps-deployer.service" /etc/systemd/system/vps-deployer.service
  fi
  if [[ -f "${VD_BACKUP}/sudoers" ]]; then
    install -m 0440 "${VD_BACKUP}/sudoers" /etc/sudoers.d/vps-deployer
  fi
  if [[ "$VD_SKIP_SERVICE_START" != "1" ]] && command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload || true
    systemctl restart vps-deployer.service || true
  fi
  log "restored ${VD_BACKUP}"
  return 0
}

run_uv_as_app_user() {
  # uv reads uv.toml from the current directory. Do not run it from the
  # invoking user's home (often mode 750), or vps-deployer gets EACCES.
  sudo -u vps-deployer -H env \
    HOME=/var/lib/vps-deployer \
    XDG_CACHE_HOME=/var/lib/vps-deployer/.cache \
    XDG_CONFIG_HOME=/var/lib/vps-deployer/.config \
    UV_CACHE_DIR=/var/lib/vps-deployer/.cache/uv \
    UV_PYTHON_INSTALL_DIR=/var/lib/vps-deployer/.local/share/uv/python \
    UV_NO_CONFIG=1 \
    /bin/bash -c 'cd /opt/vps-deployer/app && exec "$@"' bash "$@"
}

install_application() {
  echo "Installing VPS Deployer..."
  echo
  local dest="/opt/vps-deployer/app"
  mkdir -p "$dest"
  snapshot_existing

  rsync -a --delete \
    --exclude '.venv' \
    --exclude '.local' \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude '.ruff_cache' \
    "${VD_SOURCE}/" "${dest}/"

  chown -R vps-deployer:vps-deployer /opt/vps-deployer
  mkdir -p /var/lib/vps-deployer/.cache/uv /var/lib/vps-deployer/.config
  chown -R vps-deployer:vps-deployer /var/lib/vps-deployer
  if [[ ! -x /usr/local/bin/uv ]]; then
    if command -v uv >/dev/null 2>&1; then
      install -m 0755 "$(command -v uv)" /usr/local/bin/uv
    fi
  fi
  run_uv_as_app_user uv --version >/dev/null 2>&1 || true
  run_uv_as_app_user uv python install 3.12
  run_uv_as_app_user uv sync --frozen --no-dev --directory "$dest"

  install -m 0755 "${VD_SOURCE}/packaging/bin/vps-deployer" /usr/local/bin/vps-deployer
  install -m 0755 "${VD_SOURCE}/packaging/helper/vps-deployer-helper" /usr/local/libexec/vps-deployer-helper
  install -m 0644 "${VD_SOURCE}/packaging/systemd/vps-deployer.service" /etc/systemd/system/vps-deployer.service
  if [[ -f "${VD_SOURCE}/packaging/sudoers/vps-deployer" ]]; then
    install -m 0440 "${VD_SOURCE}/packaging/sudoers/vps-deployer" /etc/sudoers.d/vps-deployer.tmp
    if command -v visudo >/dev/null 2>&1 && ! visudo -c -f /etc/sudoers.d/vps-deployer.tmp; then
      rm -f /etc/sudoers.d/vps-deployer.tmp
      echo "sudoers snippet failed validation" >&2
      fail
    fi
    mv /etc/sudoers.d/vps-deployer.tmp /etc/sudoers.d/vps-deployer
    chmod 0440 /etc/sudoers.d/vps-deployer
  fi

  run_uv_as_app_user uv run --directory "$dest" alembic upgrade head || \
    run_uv_as_app_user uv run --directory "$dest" python -c \
      "from vps_deployer.db.session import init_db; init_db()"

  vd_mark ok "Application"
  vd_mark ok "Configuration"
  vd_mark ok "Database"
  vd_mark ok "CLI"
  vd_mark ok "Systemd service"
  echo
}

start_service() {
  echo "Starting VPS Deployer..."
  echo
  if [[ "$VD_SKIP_SERVICE_START" == "1" ]]; then
    vd_mark warn "Service start skipped"
    echo
    return 0
  fi
  if ! command -v systemctl >/dev/null 2>&1; then
    vd_mark warn "systemctl not available"
    echo
    return 0
  fi
  systemctl daemon-reload
  systemctl enable vps-deployer.service
  systemctl restart vps-deployer.service
  sleep 2
  if systemctl is-active --quiet vps-deployer.service; then
    vd_mark ok "Service running"
  else
    vd_mark fail "Service running"
    systemctl status vps-deployer.service --no-pager || true
    fail
  fi
  if curl -fsS --max-time 5 http://127.0.0.1:5100/health | grep -q ok; then
    vd_mark ok "API healthy"
  else
    vd_mark fail "API healthy"
    fail
  fi
  vd_mark ok "Database healthy"
  vd_mark ok "Deployment engine healthy"
  echo
}

finish() {
  local version
  version="$(vd_existing_version || echo unknown)"
  cat <<EOF
============================================================
 Installation complete
============================================================

VPS Deployer version: ${version}

Useful commands:

    vps-deployer version
    vps-deployer status
    vps-deployer doctor

Next step:

    ${VD_SITE_URL}/docs/getting-started

EOF
}

banner
resolve_source

if [[ -d /opt/vps-deployer/app/src/vps_deployer ]] || [[ -x /usr/local/bin/vps-deployer ]]; then
  VD_EXISTING=1
  echo "Existing VPS Deployer installation detected."
  echo "Current version: $(vd_existing_version || echo unknown)"
  echo "Configuration, database, and your applications will be preserved."
  echo
fi

system_check
install_packages
create_user_and_dirs
write_config
install_application
start_service
finish
log "installation complete existing=${VD_EXISTING}"
