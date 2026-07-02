#!/usr/bin/env bash
set -Eeuo pipefail

RELEASE_URL="${CVD_RELEASE_URL:-}"
SHA256_URL="${CVD_RELEASE_SHA256_URL:-}"
SHA256_VALUE="${CVD_RELEASE_SHA256:-}"
KEEP_ARCHIVE=0
INSTALL_ARGS=()

usage() {
  cat <<'HELP'
CVD Web cloud release installer

Downloads a release archive from cloud storage, verifies it when a checksum is
provided, extracts it to a temporary directory, and runs the bundled install.sh.

Usage:
  scripts/install_from_release.sh --url URL [--sha256 HEX|--sha256-url URL] [--] [install.sh args]

Examples:
  scripts/install_from_release.sh --url https://storage.example.com/cvd-web/v0.9.0/cvd-web-v0.9.0.tar.gz -- --target local
  CVD_RELEASE_URL=https://github.com/org/cvd-web/releases/latest/download/cvd-web.tar.gz scripts/install_from_release.sh -- --target wsl2 --unattended

Options before -- are consumed by this wrapper:
  --url URL          Release archive URL (.tar.gz, .tgz, .tar, or .zip)
  --sha256 HEX      Expected archive SHA-256 hex digest
  --sha256-url URL  URL of a checksum file; first 64-hex token is used
  --keep-archive    Keep downloaded archive in the temp directory for debugging
  -h, --help        Show this help

Arguments after -- are passed directly to install.sh. If no target is provided,
install.sh auto-detects local vs WSL2.
HELP
}

fail() { printf '[CVD release] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[CVD release] %s\n' "$*"; }
need_command() { command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"; }

while (($#)); do
  case "$1" in
    --url) RELEASE_URL="${2:-}"; shift 2 ;;
    --sha256) SHA256_VALUE="${2:-}"; shift 2 ;;
    --sha256-url) SHA256_URL="${2:-}"; shift 2 ;;
    --keep-archive) KEEP_ARCHIVE=1; shift ;;
    --) shift; INSTALL_ARGS=("$@"); break ;;
    -h|--help) usage; exit 0 ;;
    *) INSTALL_ARGS+=("$1"); shift ;;
  esac
done

[[ -n "$RELEASE_URL" ]] || fail "Release URL is required. Use --url or CVD_RELEASE_URL."
[[ "$RELEASE_URL" =~ ^https?://[^[:space:]]+$ ]] || fail "Release URL must be http(s) without spaces."
[[ -z "$SHA256_URL" || "$SHA256_URL" =~ ^https?://[^[:space:]]+$ ]] || fail "Checksum URL must be http(s) without spaces."
[[ -z "$SHA256_VALUE" || "$SHA256_VALUE" =~ ^[A-Fa-f0-9]{64}$ ]] || fail "SHA-256 must be a 64-character hex digest."

need_command curl
need_command tar
need_command python3

WORKDIR="$(mktemp -d)"
cleanup() {
  if [[ "$KEEP_ARCHIVE" -eq 0 ]]; then
    rm -rf "$WORKDIR"
  else
    log "Kept temp directory: $WORKDIR"
  fi
}
trap cleanup EXIT

ARCHIVE="$WORKDIR/release"
case "$RELEASE_URL" in
  *.tar.gz|*.tgz) ARCHIVE="$ARCHIVE.tar.gz" ;;
  *.tar) ARCHIVE="$ARCHIVE.tar" ;;
  *.zip) ARCHIVE="$ARCHIVE.zip" ;;
  *) ARCHIVE="$ARCHIVE.archive" ;;
esac

log "Downloading release: $RELEASE_URL"
curl -fL --retry 3 --connect-timeout 15 --max-time 600 -o "$ARCHIVE" "$RELEASE_URL"

if [[ -n "$SHA256_URL" ]]; then
  log "Downloading checksum: $SHA256_URL"
  SHA256_VALUE="$(curl -fL --retry 3 --connect-timeout 15 --max-time 120 "$SHA256_URL" | sed -nE 's/.*([A-Fa-f0-9]{64}).*/\1/p' | head -n 1)"
  [[ -n "$SHA256_VALUE" ]] || fail "Could not parse SHA-256 from checksum URL."
fi

if [[ -n "$SHA256_VALUE" ]]; then
  log "Verifying archive SHA-256"
  ACTUAL_SHA256="$(python3 - "$ARCHIVE" <<'PY'
import hashlib, pathlib, sys
path = pathlib.Path(sys.argv[1])
h = hashlib.sha256()
with path.open('rb') as fh:
    for chunk in iter(lambda: fh.read(1024 * 1024), b''):
        h.update(chunk)
print(h.hexdigest())
PY
)"
  [[ "${ACTUAL_SHA256,,}" == "${SHA256_VALUE,,}" ]] || fail "SHA-256 mismatch: expected $SHA256_VALUE, got $ACTUAL_SHA256"
fi

EXTRACT_DIR="$WORKDIR/extract"
mkdir -p "$EXTRACT_DIR"
case "$ARCHIVE" in
  *.tar.gz|*.tgz) tar -xzf "$ARCHIVE" -C "$EXTRACT_DIR" ;;
  *.tar) tar -xf "$ARCHIVE" -C "$EXTRACT_DIR" ;;
  *.zip)
    need_command unzip
    unzip -q "$ARCHIVE" -d "$EXTRACT_DIR"
    ;;
  *)
    if tar -tzf "$ARCHIVE" >/dev/null 2>&1; then
      tar -xzf "$ARCHIVE" -C "$EXTRACT_DIR"
    elif tar -tf "$ARCHIVE" >/dev/null 2>&1; then
      tar -xf "$ARCHIVE" -C "$EXTRACT_DIR"
    else
      fail "Unknown archive format. Use .tar.gz, .tgz, .tar, or .zip."
    fi
    ;;
esac

mapfile -t INSTALLERS < <(find "$EXTRACT_DIR" -maxdepth 3 -type f -name install.sh | sort)
[[ "${#INSTALLERS[@]}" -gt 0 ]] || fail "Downloaded archive does not contain install.sh."
INSTALLER="${INSTALLERS[0]}"
RELEASE_DIR="$(cd -- "$(dirname -- "$INSTALLER")" && pwd)"
[[ -d "$RELEASE_DIR/cvd_web" ]] || fail "install.sh was found, but cvd_web/ is missing next to it."
chmod +x "$INSTALLER"

log "Installing from extracted release: $RELEASE_DIR"
log "Forwarding install.sh args: ${INSTALL_ARGS[*]:-(none)}"
exec "$INSTALLER" "${INSTALL_ARGS[@]}"
