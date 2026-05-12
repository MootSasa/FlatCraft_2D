#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m nuitka \
  --onefile \
  --standalone \
  --enable-plugin=multiprocessing \
  --output-filename=flatcraft \
  --output-dir=builds \
  \
  --include-package=src \
  --include-package=arcade \
  --include-package=pydantic \
  --include-package=pydantic_core \
  --include-package=scipy \
  --include-package=perlin_noise \
  --include-package=psutil \
  --include-package=PIL \
  \
  --nofollow-import-to=*.tests \
  --include-data-dir=assets=assets \
  \
  --assume-yes-for-downloads \
  src/main.py
