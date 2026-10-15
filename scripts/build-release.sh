#!/usr/bin/env bash
#
# Builds one release into dist/:
#
#   caelum-<version>-py3-none-any.whl   backend + bundled local web UI
#   manifest.json                       what cameras read to find the update
#   install.sh                          the one-line system installer
#   SHA256SUMS
#
# Publishing a release = uploading these files: CI attaches them to a GitHub
# release (.github/workflows/release.yml); to host an update channel anywhere
# else, copy them to any static web server and point update.manifest_url at
# that copy of manifest.json.
#
#   scripts/build-release.sh [--notes "text"] [--version X.Y.Z]
#
# --version overrides pyproject's version for this build only (for testing
# the update path with throwaway versions); pyproject.toml is restored.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

NOTES=""
VERSION_OVERRIDE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --notes) NOTES="$2"; shift 2 ;;
    --version) VERSION_OVERRIDE="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 64 ;;
  esac
done

echo "==> Web UI"
pnpm -C web install --frozen-lockfile
pnpm -C web --filter local-web build
rm -rf src/caelum/webui
cp -r web/apps/local-web/dist src/caelum/webui

echo "==> Wheel"
rm -rf dist
if [[ -n "$VERSION_OVERRIDE" ]]; then
  cp pyproject.toml pyproject.toml.orig
  trap 'mv pyproject.toml.orig pyproject.toml' EXIT
  sed -i "0,/^version = .*/s//version = \"$VERSION_OVERRIDE\"/" pyproject.toml
fi
uv build --wheel --out-dir dist
WHEEL="$(cd dist && ls caelum-*.whl)"
VERSION="$(echo "$WHEEL" | sed -n 's/^caelum-\([^-]*\)-.*\.whl$/\1/p')"

# Only the wheel should carry this copy; left in the source tree it would
# shadow web/'s own build output in a dev checkout (see settings.py).
rm -rf src/caelum/webui

# A wheel without the UI would install fine and serve nothing — refuse it.
unzip -l "dist/$WHEEL" | grep -q "caelum/webui/index.html" || { echo "UI missing from $WHEEL" >&2; exit 1; }

echo "==> Manifest"
cp scripts/install-system.sh dist/install.sh
python3 - "$VERSION" "$WHEEL" "$NOTES" <<'EOF'
import hashlib, json, sys
version, wheel, notes = sys.argv[1:]
sha = hashlib.sha256(open(f"dist/{wheel}", "rb").read()).hexdigest()
manifest = {"releases": [{"version": version, "wheel": wheel, "sha256": sha, "notes": notes}]}
open("dist/manifest.json", "w").write(json.dumps(manifest, indent=2) + "\n")
EOF
(cd dist && sha256sum "$WHEEL" install.sh manifest.json > SHA256SUMS)

ls -l dist
echo "Built caelum $VERSION."
