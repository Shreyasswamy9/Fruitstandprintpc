#!/usr/bin/env bash
# Build a self-contained release tarball on a development machine.
#   deploy/make-release.sh            -> dist/printhub-<version>.tar.gz
#   deploy/make-release.sh --wheels   -> also bundles Python wheels for an offline install on the station
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/backend/printhub/__init__.py")"
OUT="$ROOT/dist"
STAGE="$(mktemp -d)/printhub-$VERSION"

echo "Building Print Hub $VERSION"
(cd "$ROOT/frontend" && npm ci && npm run build)

mkdir -p "$STAGE" "$OUT"
rsync -a --exclude '.venv' --exclude '__pycache__' --exclude '.pytest_cache' "$ROOT/backend" "$STAGE/"
mkdir -p "$STAGE/frontend" && cp -R "$ROOT/frontend/dist" "$STAGE/frontend/dist"
cp -R "$ROOT/deploy" "$ROOT/docs" "$STAGE/"
cp "$ROOT/README.md" "$STAGE/"

if [[ "${1:-}" == "--wheels" ]]; then
  # Wheels for the station (Linux Mint 22 = Ubuntu 24.04, Python 3.12, x86_64).
  python3 -m pip download --dest "$STAGE/wheels" --only-binary=:all: \
    --platform manylinux2014_x86_64 --platform manylinux_2_28_x86_64 --python-version 3.12 \
    "$ROOT/backend" setuptools wheel || {
      echo "Wheel download failed; the station will need internet access for pip." >&2; }
fi

tar -C "$(dirname "$STAGE")" -czf "$OUT/printhub-$VERSION.tar.gz" "printhub-$VERSION"
echo "Release: $OUT/printhub-$VERSION.tar.gz"
