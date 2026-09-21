#!/usr/bin/env bash
# Shared installer helpers. Safe to source from tests.
# shellcheck disable=SC2034

VD_SITE_URL_DEFAULT="https://vps-deployer.onebitstack.com"
VD_MIN_CPU=2
VD_MIN_RAM_MB=2048
VD_MIN_DISK_GB=10
VD_HARD_RAM_MB=512
VD_HARD_DISK_GB=2

vd_version_ge() {
  local current="$1"
  local minimum="$2"
  [[ "$(printf '%s\n%s\n' "$minimum" "$current" | sort -V | head -n 1)" == "$minimum" ]]
}

vd_os_supported() {
  local distro="${1:-}"
  local version="${2:-}"
  distro="$(printf '%s' "$distro" | tr '[:upper:]' '[:lower:]')"
  case "$distro" in
    ubuntu)
      [[ -n "$version" ]] && vd_version_ge "$version" "22.04"
      ;;
    debian)
      [[ -n "$version" ]] && vd_version_ge "$version" "12"
      ;;
    *)
      return 1
      ;;
  esac
}

vd_ubuntu_lts_supported() {
  local version="${1:-}"
  if [[ ! "$version" =~ ^([0-9]{2})\.04$ ]]; then
    return 1
  fi
  local year="${BASH_REMATCH[1]}"
  [[ "$((10#$year % 2))" -eq 0 ]] && vd_version_ge "$version" "22.04"
}

vd_parse_os_release() {
  local file="${1:-/etc/os-release}"
  VD_OS_ID=""
  VD_OS_VERSION=""
  VD_OS_PRETTY=""
  if [[ ! -f "$file" ]]; then
    return 1
  fi
  # shellcheck disable=SC1090
  . "$file"
  VD_OS_ID="${ID:-}"
  VD_OS_VERSION="${VERSION_ID:-}"
  VD_OS_PRETTY="${PRETTY_NAME:-$VD_OS_ID $VD_OS_VERSION}"
}

vd_arch_from_uname() {
  case "${1:-}" in
    x86_64|amd64)
      printf '%s\n' "amd64"
      ;;
    aarch64|arm64)
      printf '%s\n' "arm64"
      ;;
    *)
      printf '%s\n' "unsupported"
      return 1
      ;;
  esac
}

vd_validate_semver() {
  local version="${1:-}"
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][A-Za-z0-9.-]+)?$ ]]
}

vd_should_write_file() {
  local path="${1:-}"
  if [[ -z "$path" ]]; then
    return 1
  fi
  if [[ -e "$path" ]]; then
    return 1
  fi
  return 0
}

vd_preserve_existing() {
  local path="${1:-}"
  [[ -e "$path" ]]
}

vd_is_https_url() {
  local url="${1:-}"
  [[ "$url" =~ ^https:// ]]
}

vd_tar_members_safe() {
  local archive="${1:-}"
  local member
  if [[ -z "$archive" || ! -f "$archive" ]]; then
    return 1
  fi
  while IFS= read -r member; do
    [[ -z "$member" ]] && continue
    case "$member" in
      /*|*..*)
        return 1
        ;;
    esac
  done < <(tar -tzf "$archive")
  return 0
}

vd_safe_project_name() {
  local name="${1:-}"
  [[ "$name" =~ ^[a-z][a-z0-9-]{1,62}$ ]] && [[ "$name" != *..* ]]
}

vd_bytes_to_mb() {
  local bytes="${1:-0}"
  printf '%s\n' "$((bytes / 1024 / 1024))"
}

vd_kb_to_mb() {
  local kb="${1:-0}"
  printf '%s\n' "$((kb / 1024))"
}

vd_detect_cpu() {
  local count
  count="$(getconf _NPROCESSORS_ONLN 2>/dev/null || nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 0)"
  printf '%s\n' "${count:-0}"
}

vd_detect_ram_mb() {
  if [[ -r /proc/meminfo ]]; then
    local kb
    kb="$(awk '/MemTotal:/ { print $2 }' /proc/meminfo)"
    vd_kb_to_mb "$kb"
    return 0
  fi
  if command -v sysctl >/dev/null 2>&1; then
    local bytes
    bytes="$(sysctl -n hw.memsize 2>/dev/null || echo 0)"
    vd_bytes_to_mb "$bytes"
    return 0
  fi
  printf '%s\n' "0"
}

vd_detect_disk_gb() {
  local target="${1:-/}"
  df -Pk "$target" 2>/dev/null | awk 'NR==2 { printf "%d\n", $4 / 1024 / 1024 }'
}

vd_check_internet() {
  local url="${1:-$VD_SITE_URL_DEFAULT}"
  if ! vd_is_https_url "$url"; then
    return 1
  fi
  if command -v curl >/dev/null 2>&1; then
    curl -fsSI --max-time 10 "$url" >/dev/null 2>&1 && return 0
  fi
  return 1
}

vd_existing_version() {
  if command -v vps-deployer >/dev/null 2>&1; then
    vps-deployer version 2>/dev/null || true
    return 0
  fi
  if [[ -x /opt/vps-deployer/app/.venv/bin/vps-deployer ]]; then
    /opt/vps-deployer/app/.venv/bin/vps-deployer version 2>/dev/null || true
    return 0
  fi
  return 1
}

vd_mark() {
  local ok="${1:-}"
  local message="${2:-}"
  if [[ "$ok" == "ok" ]]; then
    printf '✓ %s\n' "$message"
  elif [[ "$ok" == "warn" ]]; then
    printf '⚠ %s\n' "$message"
  else
    printf '✗ %s\n' "$message"
  fi
}
