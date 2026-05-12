@echo off
setlocal

cd /d "%~dp0\.."

set CONSOLE_MODE=disable

.\winvenv\Scripts\python.exe -m nuitka ^
  --onefile ^
  --standalone ^
  --windows-console-mode=%CONSOLE_MODE% ^
  --enable-plugin=multiprocessing ^
  --windows-icon-from-ico=assets/icons/flatcraft.ico ^
  --output-filename=flatcraft.exe ^
  --output-dir=builds ^
  ^
  --include-package=src ^
  --include-package=arcade ^
  --include-package=pydantic ^
  --include-package=pydantic_core ^
  --include-package=scipy ^
  --include-package=perlin_noise ^
  --include-package=psutil ^
  --include-package=PIL ^
  ^
  --nofollow-import-to=*.tests ^
  --include-data-dir=assets=assets ^
  ^
  --assume-yes-for-downloads ^
  --msvc=latest ^
  src\main.py