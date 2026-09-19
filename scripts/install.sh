#!/usr/bin/env bash
# One-time setup: create local config/data directories. Sky-state uses
# astropy's builtin offline ephemeris (see control/skystate.py) — there is
# no external ephemeris file to seed, and no network access is ever needed
# at runtime.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

mkdir -p ./data/raw ./data/thumbnails ./data/derivatives ./data/pending-upload ./config

if [ ! -f ./config/config.json ] && [ -f ./config/default.json ]; then
    cp ./config/default.json ./config/config.json
    echo "seeded config/config.json from config/default.json"
fi

echo "done."
