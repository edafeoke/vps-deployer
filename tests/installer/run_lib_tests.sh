#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck source=../../installer/lib.sh
. "${ROOT}/installer/lib.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

pass() {
  echo "PASS: $*"
}

vd_os_supported ubuntu 24.04 || fail "ubuntu 24.04 should be supported"
vd_os_supported ubuntu 22.04 || fail "ubuntu 22.04 should be supported"
vd_os_supported debian 12 || fail "debian 12 should be supported"
vd_os_supported debian 13 || fail "debian 13 should be supported"
vd_ubuntu_lts_supported 24.04 || fail "ubuntu 24.04 LTS should be supported"
vd_ubuntu_lts_supported 26.04 || fail "ubuntu 26.04 LTS should be supported"
if vd_ubuntu_lts_supported 25.04; then
  fail "ubuntu 25.04 should not be identified as LTS"
fi
if vd_os_supported ubuntu 20.04; then
  fail "ubuntu 20.04 should be rejected"
fi
if vd_os_supported fedora 40; then
  fail "fedora should be rejected"
fi
pass "os detection"

[[ "$(vd_arch_from_uname x86_64)" == "amd64" ]] || fail "x86_64"
[[ "$(vd_arch_from_uname aarch64)" == "arm64" ]] || fail "aarch64"
if vd_arch_from_uname ppc64le >/dev/null; then
  fail "ppc64le should be rejected"
fi
pass "architecture detection"

vd_validate_semver 1.2.0 || fail "1.2.0"
if vd_validate_semver latest; then
  fail "latest is not semver"
fi
pass "version validation"

tmp="$(mktemp)"
if vd_should_write_file "$tmp"; then
  fail "existing file must be preserved"
fi
rm -f "$tmp"
vd_should_write_file "$tmp" || fail "missing file should be writable"
pass "idempotent config preservation"

vd_is_https_url "https://vps-deployer.onebitstack.com/install.sh" || fail "https url"
if vd_is_https_url "http://example.com/install.sh"; then
  fail "http url must be rejected"
fi
pass "https only downloads"

vd_safe_project_name my-next-app || fail "valid project"
if vd_safe_project_name '../etc/passwd'; then
  fail "path traversal project name"
fi
if vd_safe_project_name 'app;reboot'; then
  fail "injection project name"
fi
pass "project name safety"

safe_tar="$(mktemp -d)"
printf 'ok\n' >"${safe_tar}/readme"
COPYFILE_DISABLE=1 tar -czf "${safe_tar}/safe.tgz" -C "$safe_tar" readme
vd_tar_members_safe "${safe_tar}/safe.tgz" || fail "safe tarball"
python3 - "$safe_tar/unsafe.tgz" <<'PY'
import sys
import tarfile

path = sys.argv[1]
with tarfile.open(path, "w:gz") as archive:
    info = tarfile.TarInfo("../etc/passwd")
    info.size = 0
    archive.addfile(info)
PY
if vd_tar_members_safe "${safe_tar}/unsafe.tgz"; then
  fail "unsafe tarball must be rejected"
fi
rm -rf "$safe_tar"
pass "tarball member safety"

echo "All installer library tests passed."
