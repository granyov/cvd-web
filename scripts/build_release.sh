#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${CVD_RELEASE_OUT_DIR:-${ROOT_DIR}/dist}"
VERSION="${CVD_RELEASE_VERSION:-}"
ARCHIVE_NAME=""

usage() {
  cat <<'HELP'
CVD Web release builder

Builds a self-contained tar.gz archive that can be copied into WSL2 or a VPS
and installed with the bundled install.sh.

Usage:
  scripts/build_release.sh [--version vX.Y.Z] [--out-dir DIR] [--name FILE]

Examples:
  scripts/build_release.sh --version v0.9.1
  scripts/build_release.sh --out-dir /tmp/cvd-release --name cvd-web-v0.9.1.tar.gz
HELP
}

fail() { printf '[CVD build] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[CVD build] %s\n' "$*"; }

while (($#)); do
  case "$1" in
    --version) VERSION="${2:-}"; shift 2 ;;
    --out-dir) OUT_DIR="${2:-}"; shift 2 ;;
    --name) ARCHIVE_NAME="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done

if [[ -z "$VERSION" ]]; then
  VERSION="$(python3 - <<'PY'
from cvd_web.versions import APP_VERSION
print(APP_VERSION)
PY
)"
fi
[[ "$VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([A-Za-z0-9._-]+)?$ ]] || fail "Version must look like v0.9.1"
ARCHIVE_NAME="${ARCHIVE_NAME:-cvd-web-${VERSION}.tar.gz}"
[[ "$ARCHIVE_NAME" == *.tar.gz ]] || fail "Archive name must end with .tar.gz"

mkdir -p "$OUT_DIR"
ARCHIVE_PATH="${OUT_DIR}/${ARCHIVE_NAME}"
CHECKSUM_PATH="${ARCHIVE_PATH}.sha256"

log "Running Python tests before packaging"
(cd "$ROOT_DIR" && python3 -m unittest discover -s tests -p 'test_*.py')

log "Building $ARCHIVE_PATH"
tar -C "$ROOT_DIR" \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='data' \
  --exclude='backups' \
  --exclude='dist' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  -czf "$ARCHIVE_PATH" .

python3 - "$ARCHIVE_PATH" >"$CHECKSUM_PATH" <<'PY'
import hashlib, pathlib, sys
path = pathlib.Path(sys.argv[1])
h = hashlib.sha256()
with path.open("rb") as fh:
    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
        h.update(chunk)
print(f"{h.hexdigest()}  {path.name}")
PY

log "Archive:  $ARCHIVE_PATH"
log "Checksum: $CHECKSUM_PATH"
