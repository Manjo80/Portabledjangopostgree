#Requires -Version 5.1
<#
.SYNOPSIS
    Portable Django Manager - Umgebungs-Setup

.DESCRIPTION
    Laedt eingebettetes Python, portables PostgreSQL und portables nginx
    herunter und richtet die Laufzeitumgebung ein.

    Nach diesem Skript:
      python\              <- Python 3.12 (eingebettet, kein System-Python noetig)
      postgres\            <- PostgreSQL 16 (portabel, keine Installation noetig)
      nginx\nginx-1.26.3\  <- nginx (portabel, Reverse-Proxy + statische Dateien)

    Danach: PortableDjangoManager.exe starten (oder: python main.py)

.PARAMETER PythonVersion
    Python-Version fuer das eingebettete Paket. Standard: 3.12.8

.PARAMETER PostgresDownloadUrl
    Direkter Download-URL fuer PostgreSQL Windows x64 Binaries ZIP.
    Standard: EDB PostgreSQL 16.6

.PARAMETER NginxVersion
    nginx-Version die heruntergeladen wird. Standard: 1.26.3

.PARAMETER SkipPostgresDownload
    Ueberspringt den PostgreSQL-Download (wenn schon vorhanden).
    ZIP muss als 'postgresql-binaries.zip' im gleichen Verzeichnis liegen.

.PARAMETER SkipNginxDownload
    Ueberspringt den nginx-Download (wenn schon vorhanden oder nicht benoetigt).

.EXAMPLE
    .\setup_environment.ps1
.EXAMPLE
    .\setup_environment.ps1 -SkipPostgresDownload
.EXAMPLE
    .\setup_environment.ps1 -SkipNginxDownload
.EXAMPLE
    .\setup_environment.ps1 -NginxVersion "1.27.0"
#>

[CmdletBinding()]
param(
    [string]$PythonVersion       = "3.12.8",
    [string]$PostgresDownloadUrl = "",
    [string]$NginxVersion        = "1.26.3",
    [switch]$SkipPostgresDownload,
    [switch]$SkipNginxDownload
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"

$Root        = $PSScriptRoot
$PythonDir   = Join-Path $Root "python"
$PostgresDir = Join-Path $Root "postgres"
$NginxDir    = Join-Path $Root "nginx"
$TempDir     = Join-Path $env:TEMP "pdt-setup-$(Get-Random -Maximum 99999)"
$PgVersion   = "16.6-1"

if (-not $PostgresDownloadUrl) {
    $PostgresDownloadUrl = "https://get.enterprisedb.com/postgresql/postgresql-$PgVersion-windows-x64-binaries.zip"
}

function Write-Step { param([string]$M) Write-Host "`n  >> $M" -ForegroundColor Cyan }
function Write-OK   { param([string]$M) Write-Host "     OK  $M" -ForegroundColor Green }
function Write-Fail { param([string]$M) Write-Host "     ERR $M" -ForegroundColor Red; throw $M }

function Invoke-Download {
    param([string]$Url, [string]$Dest, [string]$Label)
    if (Test-Path $Dest) { Write-OK "$Label bereits vorhanden."; return }
    Write-Host "     ... $Label herunterladen" -NoNewline
    $delay = 2
    for ($i = 1; $i -le 4; $i++) {
        try {
            Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
            Write-Host " OK" -ForegroundColor Green
            return
        } catch {
            if ($i -eq 4) { Write-Host ""; Write-Fail "Download fehlgeschlagen: $Url`n$_" }
            Write-Host "." -NoNewline; Start-Sleep -Seconds $delay; $delay *= 2
        }
    }
}

Write-Host ""
Write-Host "  Portable Django Manager - Umgebungs-Setup" -ForegroundColor Cyan
Write-Host "  Python $PythonVersion + PostgreSQL $PgVersion + nginx $NginxVersion" -ForegroundColor Cyan
Write-Host ""

New-Item -ItemType Directory -Path $TempDir -Force | Out-Null

# ── Python ────────────────────────────────────────────────────────────────────
Write-Step "Python $PythonVersion herunterladen"

$PythonZip  = Join-Path $TempDir "python-embed.zip"
$GetPipFile = Join-Path $TempDir "get-pip.py"

Invoke-Download `
    -Url  "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" `
    -Dest $PythonZip `
    -Label "Python $PythonVersion (Embeddable)"

Invoke-Download `
    -Url  "https://bootstrap.pypa.io/get-pip.py" `
    -Dest $GetPipFile `
    -Label "pip-Installer"

Write-Step "Python einrichten"
if (-not (Test-Path $PythonDir)) {
    New-Item -ItemType Directory -Path $PythonDir | Out-Null
}
Expand-Archive -Path $PythonZip -DestinationPath $PythonDir -Force

# import site aktivieren (benoetigt fuer pip/site-packages)
$PthFile = Get-ChildItem $PythonDir -Filter "python*._pth" | Select-Object -First 1
if (-not $PthFile) { Write-Fail "._pth-Datei nicht gefunden." }
$pth = Get-Content $PthFile.FullName -Raw
$pth = $pth -replace '#\s*import site', 'import site'
Set-Content $PthFile.FullName $pth -NoNewline
Write-OK "site-packages aktiviert."

$PyExe = Join-Path $PythonDir "python.exe"
Write-Host "     ... pip installieren" -NoNewline
& $PyExe $GetPipFile --no-warn-script-location 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Fail "pip-Installation fehlgeschlagen." }
Write-Host " OK" -ForegroundColor Green

Write-Host "     ... Abhaengigkeiten installieren" -NoNewline
& $PyExe -m pip install customtkinter --no-warn-script-location -q 2>&1 | Out-Null
Write-Host " OK" -ForegroundColor Green
Write-OK "Python fertig."

# ── PostgreSQL ────────────────────────────────────────────────────────────────
$PgInitdb = Join-Path $PostgresDir "bin\initdb.exe"

# Wenn postgres\bin\initdb.exe schon vorhanden ist, komplett ueberspringen
if (Test-Path $PgInitdb) {
    Write-Step "PostgreSQL $PgVersion"
    Write-OK "postgres\bin\initdb.exe bereits vorhanden - uebersprungen."
} else {
    Write-Step "PostgreSQL $PgVersion herunterladen"

    $PostgresZip    = Join-Path $Root "postgresql-binaries.zip"
    $PostgresZipTmp = Join-Path $TempDir "postgresql-binaries.zip"

    if ($SkipPostgresDownload) {
        if (-not (Test-Path $PostgresZip)) {
            Write-Fail "postgresql-binaries.zip nicht gefunden neben diesem Skript.`nBitte die ZIP unter $PostgresZip ablegen oder das Flag -SkipPostgresDownload weglassen."
        }
        Copy-Item $PostgresZip $PostgresZipTmp
        Write-OK "Vorhandene PostgreSQL-ZIP wird verwendet."
    } else {
        Write-Host "     (ca. 300 MB - bitte warten)"
        Invoke-Download `
            -Url  $PostgresDownloadUrl `
            -Dest $PostgresZipTmp `
            -Label "PostgreSQL $PgVersion Windows x64"
    }

    Write-Step "PostgreSQL einrichten"
    $PgTemp = Join-Path $TempDir "pg-extract"
    New-Item -ItemType Directory $PgTemp -Force | Out-Null
    Expand-Archive -Path $PostgresZipTmp -DestinationPath $PgTemp -Force
    $PgRoot = Join-Path $PgTemp "pgsql"
    foreach ($dir in @("bin", "lib", "share")) {
        $src = Join-Path $PgRoot $dir
        if (Test-Path $src) {
            Copy-Item $src -Destination $PostgresDir -Recurse -Force
        }
    }
    Write-OK "PostgreSQL-Binaries kopiert."
}

# ── nginx ─────────────────────────────────────────────────────────────────────
$NginxExe = Join-Path $NginxDir "nginx-$NginxVersion\nginx.exe"

if ($SkipNginxDownload) {
    Write-Step "nginx $NginxVersion"
    Write-OK "nginx-Download uebersprungen (-SkipNginxDownload)."
} elseif (Test-Path $NginxExe) {
    Write-Step "nginx $NginxVersion"
    Write-OK "nginx bereits vorhanden ($NginxExe)."
} else {
    Write-Step "nginx $NginxVersion herunterladen  (ca. 1.5 MB)"

    $NginxZipUrl = "https://nginx.org/download/nginx-$NginxVersion.zip"
    $NginxZip    = Join-Path $TempDir "nginx-$NginxVersion.zip"

    Invoke-Download `
        -Url   $NginxZipUrl `
        -Dest  $NginxZip `
        -Label "nginx $NginxVersion (Windows portable)"

    Write-Step "nginx einrichten"
    New-Item -ItemType Directory -Path $NginxDir -Force | Out-Null
    Expand-Archive -Path $NginxZip -DestinationPath $NginxDir -Force

    if (Test-Path $NginxExe) {
        Write-OK "nginx $NginxVersion bereit  ($NginxExe)"
    } else {
        # Nur Warnung - nginx ist optional
        Write-Host "     WARN nginx.exe nicht gefunden nach Entpacken - nginx-Unterstuetzung nicht verfuegbar." -ForegroundColor Yellow
        Write-Host "          Erwartet: $NginxExe" -ForegroundColor Yellow
    }
}

# ── Aufraumen ─────────────────────────────────────────────────────────────────
Remove-Item $TempDir -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host "  Umgebung bereit!" -ForegroundColor Green
Write-Host ""
Write-Host "  Verzeichnisse:" -ForegroundColor White
Write-Host "    python\              Python $PythonVersion (eingebettet)" -ForegroundColor White
Write-Host "    postgres\            PostgreSQL $PgVersion (portabel)" -ForegroundColor White
if (-not $SkipNginxDownload) {
    Write-Host "    nginx\nginx-$NginxVersion\  nginx $NginxVersion (portabel)" -ForegroundColor White
}
Write-Host ""
Write-Host "  Naechste Schritte:" -ForegroundColor White
Write-Host "  1. PortableDjangoManager.exe starten  (nach build_exe.bat)" -ForegroundColor White
Write-Host "     ODER: python main.py" -ForegroundColor White
Write-Host "  2. App hinzufuegen, konfigurieren und starten" -ForegroundColor White
Write-Host "  ============================================================" -ForegroundColor Green
Write-Host ""
