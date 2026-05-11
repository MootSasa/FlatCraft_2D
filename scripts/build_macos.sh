#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m nuitka \
  --macos-create-app-bundle \
  --output-filename=flatcraft \
  --include-package=src \
  --include-package=arcade \
  --include-package=scipy \
  --include-package=numpy \
  --include-package=PIL \
  --include-package=pydantic \
  --include-package=psutil \
  --include-package=perlin_noise \
  --include-data-dir=assets=assets \
  --output-dir=builds \
  --assume-yes-for-downloads \
  src/main.py
