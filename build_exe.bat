@echo off
setlocal
chcp 65001 > nul
title Portable Django Tester - EXE Build

echo.
echo  ============================================================
echo  Portable Django Tester - EXE-Erstellung
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

echo  [1/3] Installiere Abhaengigkeiten...
pip install -r requirements.txt -q
if %ERRORLEVEL% neq 0 (
    echo  FEHLER: pip install fehlgeschlagen!
    pause
    exit /b 1
)
echo  [OK] Abhaengigkeiten installiert.

echo  [2/3] Erstelle EXE mit PyInstaller...
pyinstaller ^
    --onefile ^
    --windowed ^
    --name "PortableDjangoManager" ^
    --icon NONE ^
    --add-data "db.py;." ^
    --add-data "runner.py;." ^
    --add-data "git_manager.py;." ^
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

echo  [3/3] Kopiere EXE in dist-Verzeichnis...
if exist dist\PortableDjangoManager.exe (
    echo.
    echo  ============================================================
    echo  Fertig!
    echo  EXE: dist\PortableDjangoManager.exe
    echo.
    echo  Die EXE kann zusammen mit den Ordnern
    echo    python\     (eingebettetes Python)
    echo    postgres\   (portables PostgreSQL)
    echo  auf einem USB-Stick oder Netzlaufwerk betrieben werden.
    echo  ============================================================
) else (
    echo  FEHLER: EXE nicht gefunden!
)
echo.
pause
