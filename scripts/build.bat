@echo off
cd /d "%~dp0\.."
.\winvenv\Scripts\python.exe -m nuitka ^
  --onefile ^
  --windows-console-mode=disable ^
  --output-filename=flatcraft.exe ^
  --include-package=src ^
  --include-package=arcade ^
  --include-package=scipy ^
  --include-package=numpy ^
  --include-package=PIL ^
  --include-package=pydantic ^
  --include-package=psutil ^
  --include-package=perlin_noise ^
  --include-data-dir=assets=assets ^
  --output-dir=builds ^
  --assume-yes-for-downloads ^
  --msvc=latest ^
  src\main.py
