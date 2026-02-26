@echo off
setlocal
chcp 65001 > nul
title Portable Django Manager - EXE Build

echo.
echo  ============================================================
echo  Portable Django Manager - EXE-Erstellung
echo  ============================================================
echo.

:: Python pruefen
python --version > nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo  FEHLER: Python nicht gefunden!
    echo  Bitte Python installieren: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: Python Scripts-Ordner dynamisch zum PATH hinzufuegen
:: loest "pyinstaller is not recognized" bei User-Installationen
for /f "usebackq tokens=*" %%i in (
    `python -c "import sys,os;print(os.path.join(os.path.dirname(sys.executable),'Scripts'))"`
) do set PY_SCRIPTS=%%i
set PATH=%PY_SCRIPTS%;%PATH%
echo  [INFO] Python Scripts: %PY_SCRIPTS%

echo  [1/3] Installiere Abhaengigkeiten...
python -m pip install -r requirements.txt -q
if %ERRORLEVEL% neq 0 (
    echo  FEHLER: pip install fehlgeschlagen!
    pause
    exit /b 1
)
echo  [OK] Abhaengigkeiten installiert.

echo  [2/3] Erstelle EXE mit PyInstaller...
python -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "PortableDjangoManager" ^
    --icon NONE ^
    --add-data "db.py;." ^
    --add-data "runner.py;." ^
    --add-data "git_manager.py;." ^
    --add-data "logo.png;." ^
    --hidden-import customtkinter ^
    --hidden-import tkinter ^
    --hidden-import sqlite3 ^
    --collect-all customtkinter ^
    main.py

if %ERRORLEVEL% neq 0 (
    echo  FEHLER: PyInstaller fehlgeschlagen!
    pause
    exit /b 1
)
echo  [OK] EXE erstellt.

echo  [3/3] Kopiere EXE in Projektverzeichnis...
set EXE_SRC=dist\PortableDjangoManager.exe
set EXE_DST=%~dp0PortableDjangoManager.exe

if exist "%EXE_SRC%" (
    copy /Y "%EXE_SRC%" "%EXE_DST%" > nul
    if %ERRORLEVEL% neq 0 (
        echo  FEHLER: Kopieren fehlgeschlagen!
        pause
        exit /b 1
    )
    echo  [OK] EXE kopiert.
    echo.
    echo  ============================================================
    echo  Fertig!
    echo  EXE liegt jetzt hier:
    echo    %EXE_DST%
    echo.
    echo  Die EXE laeuft zusammen mit den Ordnern:
    echo    python\    - eingebettetes Python
    echo    postgres\  - portables PostgreSQL
    echo  auf USB-Stick oder Netzlaufwerk.
    echo.
    echo  Aufraeum-Tipp: dist\ und build\ koennen geloescht werden.
    echo  ============================================================
) else (
    echo  FEHLER: EXE nicht gefunden unter %EXE_SRC%
    echo  Bitte den PyInstaller-Log oben pruefen.
    pause
    exit /b 1
)
echo.
pause
