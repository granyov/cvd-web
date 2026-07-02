#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${GH_REPO:-}"
TAG=""
TITLE=""
NOTES_FILE="RELEASE_NOTES.md"
ARCHIVE=""
CHECKSUM=""
LATEST=1
DRAFT=0
PRERELEASE=0

usage() {
  cat <<'HELP'
CVD Web GitHub release publisher

Publishes an already built install archive to GitHub Releases with GitHub CLI.
Use non-interactive auth by exporting GH_TOKEN, or login once with `gh auth login`.

Usage:
  scripts/publish_github_release.sh --repo OWNER/REPO --tag v0.9.0 --archive PATH [options]

Options:
  --repo OWNER/REPO     GitHub repository. Can also be GH_REPO.
  --tag TAG             Release tag, for example v0.9.0.
  --title TITLE         Release title. Defaults to "CVD Web TAG".
  --notes-file PATH     Release notes markdown. Defaults to RELEASE_NOTES.md.
  --archive PATH        Built .tar.gz/.zip archive to upload.
  --checksum PATH       Checksum file to upload. Defaults to ARCHIVE.sha256 when present.
  --draft               Create/update release as draft.
  --prerelease          Mark release as prerelease.
  --not-latest          Do not mark release as latest.
  -h, --help            Show this help.

Required auth scopes for GH_TOKEN/PAT: repo for private repos, or public_repo for public repos.
HELP
}

fail() { printf '[CVD publish] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[CVD publish] %s\n' "$*"; }

while (($#)); do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --tag) TAG="${2:-}"; shift 2 ;;
    --title) TITLE="${2:-}"; shift 2 ;;
    --notes-file) NOTES_FILE="${2:-}"; shift 2 ;;
    --archive) ARCHIVE="${2:-}"; shift 2 ;;
    --checksum) CHECKSUM="${2:-}"; shift 2 ;;
    --draft) DRAFT=1; shift ;;
    --prerelease) PRERELEASE=1; shift ;;
    --not-latest) LATEST=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done

[[ -n "$REPO" ]] || fail "Repository is required. Use --repo OWNER/REPO or GH_REPO."
[[ "$REPO" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]] || fail "Repository must look like OWNER/REPO."
[[ -n "$TAG" ]] || fail "Tag is required. Use --tag vX.Y.Z."
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+([A-Za-z0-9._-]+)?$ ]] || fail "Tag must look like v0.9.0 or v0.9.0-beta.1."
[[ -n "$ARCHIVE" ]] || fail "Archive path is required."
[[ -f "$ARCHIVE" ]] || fail "Archive not found: $ARCHIVE"
[[ -f "$NOTES_FILE" ]] || fail "Release notes file not found: $NOTES_FILE"

if [[ -z "$CHECKSUM" && -f "${ARCHIVE}.sha256" ]]; then
  CHECKSUM="${ARCHIVE}.sha256"
fi
[[ -z "$CHECKSUM" || -f "$CHECKSUM" ]] || fail "Checksum file not found: $CHECKSUM"

command -v gh >/dev/null 2>&1 || fail "GitHub CLI 'gh' is not installed. Install it or publish from a machine that has gh."

gh auth status >/dev/null 2>&1 || fail "GitHub CLI is not authenticated. Export GH_TOKEN or run: gh auth login"

TITLE="${TITLE:-CVD Web ${TAG}}"
ASSETS=("$ARCHIVE")
if [[ -n "$CHECKSUM" ]]; then
  ASSETS+=("$CHECKSUM")
fi

CREATE_ARGS=("$TAG" "${ASSETS[@]}" --repo "$REPO" --title "$TITLE" --notes-file "$NOTES_FILE")
[[ "$DRAFT" -eq 1 ]] && CREATE_ARGS+=(--draft)
[[ "$PRERELEASE" -eq 1 ]] && CREATE_ARGS+=(--prerelease)
if [[ "$LATEST" -eq 1 ]]; then
  CREATE_ARGS+=(--latest)
else
  CREATE_ARGS+=(--latest=false)
fi

if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  log "Release $TAG already exists in $REPO; uploading assets with --clobber."
  gh release upload "$TAG" "${ASSETS[@]}" --repo "$REPO" --clobber
else
  log "Creating release $TAG in $REPO."
  gh release create "${CREATE_ARGS[@]}"
fi

log "Published release assets: ${ASSETS[*]}"
