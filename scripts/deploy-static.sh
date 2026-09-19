#!/usr/bin/env bash
#
# Publishes the two static sites — the view-only camera gallery and the
# documentation — to an Apache host over rsync+ssh.
#
# The camera itself never runs this: caelum's own uploader syncs the *data*
# tree (cameras.json, <slug>/thumbnails/...) into the same document root
# from wherever the camera lives. This script publishes the *apps* that read
# that data, which change only when you rebuild them.
#
#   ./scripts/deploy-static.sh user@host:/var/www/allsky
#
# Resulting layout on the host:
#
#   /var/www/allsky/            index.html + assets   (gallery)
#   /var/www/allsky/cameras.json, <slug>/...          (rsynced by caelum)
#   /var/www/allsky/docs/       index.html + assets   (documentation)
#
set -euo pipefail

TARGET="${1:-}"
if [[ -z "$TARGET" ]]; then
  echo "usage: $0 user@host:/path/to/document-root [docs-subdir]" >&2
  exit 64
fi
DOCS_SUBDIR="${2:-docs}"

cd "$(dirname "$0")/.."

echo "==> Building gallery"
# remote-web uses a relative asset base and derives its data root from the
# document's own directory, so one build works at any path — nothing to
# configure here.
pnpm --filter remote-web build

echo "==> Building documentation (base=/${DOCS_SUBDIR}/)"
# VitePress, unlike Vite, needs an absolute base baked in at build time.
DOCS_BASE="/${DOCS_SUBDIR}/" pnpm --filter docs build

echo "==> Publishing gallery to ${TARGET}"
# No --delete: the data tree caelum uploads lives in this same directory and
# must not be touched. Only the app's own files are overwritten.
rsync -av apps/remote-web/dist/ "${TARGET%/}/"

echo "==> Publishing documentation to ${TARGET%/}/${DOCS_SUBDIR}"
# --delete is safe here: this subdirectory holds nothing but the docs build,
# and stale assets from a previous version should go.
rsync -av --delete apps/docs/.vitepress/dist/ "${TARGET%/}/${DOCS_SUBDIR}/"

echo
echo "Done. Point the cameras' docs.base_url at https://<host>/${DOCS_SUBDIR}"
echo "so the local web UI deep-links into this documentation."
