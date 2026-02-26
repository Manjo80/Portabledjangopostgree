# Portable Django Manager

Ein grafisches Windows-Tool zum Verwalten und Testen mehrerer Django-Webanwendungen auf einem lokalen Windows-Rechner – ohne Installation, ohne Admin-Rechte, portabel auf USB-Stick oder Netzlaufwerk.

---

## Übersicht

Der Portable Django Manager bündelt:

- **Eingebettetes Python 3.12** – kein System-Python nötig
- **Portables PostgreSQL 16** – kein Datenbankserver nötig
- **Grafische Oberfläche** (customtkinter, Dark-Theme) zur Verwaltung mehrerer Apps
- **GitHub / Git-Integration** – Repos per HTTPS oder SSH klonen und aktualisieren

Jede verwaltete App bekommt ihre eigene PostgreSQL-Datenbank und läuft auf einem frei wählbaren Port. Ersteinrichtung (initdb, Migrationen) läuft automatisch beim ersten Start.

---

## Schnellstart

### 1. Umgebung einrichten (einmalig)

```powershell
# Skript entsperren (einmalig nach Download / USB-Kopie)
Unblock-File -Path .\setup_environment.ps1

# Anschließend ausführen
.\setup_environment.ps1
```

> **Hinweis:** PostgreSQL-Download ca. 300 MB – ausreichend Zeit einplanen.

> **PowerShell-Fehler „not digitally signed"?**
> Windows setzt beim Download oder Kopieren von USB/Netzlaufwerk ein Internet-Flag auf die Datei.
> Lösung: `Unblock-File` (siehe oben) oder einmalig mit Bypass starten:
> ```powershell
> powershell -ExecutionPolicy Bypass -File .\setup_environment.ps1
> ```
> Alle `.ps1`-Dateien im Ordner auf einmal entsperren:
> ```powershell
> Get-ChildItem C:\portable -Filter *.ps1 | Unblock-File
> ```

#### PostgreSQL-ZIP manuell bereitstellen (optional)

Falls der automatische Download nicht klappt:
1. ZIP von [enterprisedb.com/download-postgresql-binaries](https://www.enterprisedb.com/download-postgresql-binaries) herunterladen
2. Als `postgresql-binaries.zip` neben das Skript legen
3. Skript mit `-SkipPostgresDownload` erneut starten:

```powershell
.\setup_environment.ps1 -SkipPostgresDownload
```

---

### 2. Tool starten

**Direkt mit Python:**
```cmd
python main.py
```

**Als EXE (nach Build):**
```
PortableDjangoManager.exe
```

---

### 3. EXE erstellen (Windows)

```cmd
build_exe.bat
```

Erstellt `dist\PortableDjangoManager.exe` mit PyInstaller.
Die EXE funktioniert auf jedem Windows 10/11 (64-Bit) ohne Python-Installation – vorausgesetzt `python\` und `postgres\` liegen daneben.

---

## Verzeichnisstruktur

```
PortableDjangoManager\
│
├── PortableDjangoManager.exe   ← Hauptprogramm (nach build_exe.bat)
├── main.py                     ← Hauptprogramm (Quellcode)
├── db.py                       ← SQLite-Konfigurationsspeicher
├── runner.py                   ← Prozess-Manager (Django + PostgreSQL)
├── git_manager.py              ← Git-Integration (Clone / Pull / SSH)
├── requirements.txt            ← Python-Abhängigkeiten
├── build_exe.bat               ← EXE-Builder (PyInstaller)
├── setup_environment.ps1       ← Lädt Python + PostgreSQL herunter
│
├── python\                     ← Eingebettetes Python 3.12 (nach Setup)
├── postgres\                   ← Portables PostgreSQL 16 (nach Setup)
│
├── apps.db                     ← SQLite mit App-Konfigurationen (auto)
├── repos\                      ← Lokale Git-Klone (auto bei GitHub-Apps)
│   └── meine_app\
├── data\                       ← PostgreSQL-Datenbankdaten pro App (auto)
│   └── app_1\
└── logs\                       ← Logdateien (auto)
```

---

## App hinzufügen

Im Hauptfenster auf **＋ App hinzufügen** klicken.

### Quelle: Lokaler Ordner

Beliebiges Django-Projektverzeichnis auf dem PC oder Netzlaufwerk auswählen. Das Verzeichnis muss eine `manage.py` enthalten.

### Quelle: GitHub / Git-Repository

| Feld | Beschreibung |
|---|---|
| **Repository-URL** | HTTPS: `https://github.com/user/repo`<br>SSH: `git@github.com:user/repo.git` |
| **Branch** | Gewünschter Branch, z. B. `main` oder `develop` |
| **SSH-Schlüssel** *(optional)* | Pfad zum privaten SSH-Schlüssel, z. B. `C:\Users\max\.ssh\id_rsa`<br>Leer lassen für HTTPS oder Standard-SSH-Konfiguration |

Beim Speichern wird das Repository sofort geklont (`git clone --depth 1`).

---

## Umgebungsvariablen & .env-Datei

Im App-Dialog gibt es den Abschnitt **Umgebungsvariablen** mit folgenden Feldern:

| Feld | Standard | Bedeutung |
|---|---|---|
| **Settings-Modul** | `core.settings` | `DJANGO_SETTINGS_MODULE` – Pfad zum Django-Settings-Modul, z. B. `myapp.settings.dev` |
| **Allowed Hosts** | `localhost,127.0.0.1` | Kommagetrennte Liste erlaubter Hosts; wichtig wenn die App über eine IP oder einen Hostnamen erreichbar sein soll |
| **SECRET_KEY** | *(leer)* | Überschreibt den `SECRET_KEY` aus `settings.py`. Mit ⟳ wird automatisch ein sicherer Zufallswert erzeugt |
| **Weitere Vars** | – | Beliebige eigene KEY=VALUE-Paare (z. B. API-Keys, E-Mail-Config, Feature-Flags) |

### .env-Datei wird automatisch erstellt

Beim **Start** einer App schreibt das Tool automatisch eine `.env`-Datei ins App-Quellverzeichnis. Inhalt:

```
DEBUG="True"
ALLOWED_HOSTS="localhost,127.0.0.1"
DJANGO_SETTINGS_MODULE=core.settings
DB_NAME=meine_app
DB_USER=meine_app
DB_PASS=<generiertes-passwort>
DB_HOST=127.0.0.1
DB_PORT=5433
DATABASE_URL="postgresql://meine_app:passwort@127.0.0.1:5433/meine_app"
# + alle weiteren konfigurierten Vars
```

Die `.env` wird bei jedem Start aktualisiert – Änderungen im GUI sind sofort beim nächsten Start wirksam.

### settings.py anpassen

Die Django-`settings.py` muss die Variablen aus der `.env` einlesen. Empfohlen mit **python-decouple** oder **django-environ**:

**Variante 1 – python-decouple** (`pip install python-decouple`):

```python
from decouple import config

SECRET_KEY = config("SECRET_KEY", default="dev-only-insecure-key")
DEBUG = config("DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost").split(",")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME":     config("DB_NAME"),
        "USER":     config("DB_USER"),
        "PASSWORD": config("DB_PASS"),
        "HOST":     config("DB_HOST", default="127.0.0.1"),
        "PORT":     config("DB_PORT", default="5432"),
    }
}
```

**Variante 2 – os.environ** (ohne externe Abhängigkeit):

```python
import os

SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.environ.get("DEBUG", "True") == "True"
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost").split(",")

DATABASES = {
    "default": {
        "ENGINE":   "django.db.backends.postgresql",
        "NAME":     os.environ.get("DB_NAME", "myapp"),
        "USER":     os.environ.get("DB_USER", "myapp"),
        "PASSWORD": os.environ.get("DB_PASS", ""),
        "HOST":     os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT":     os.environ.get("DB_PORT", "5432"),
    }
}
```

> **Hinweis:** Die Variablen werden als Prozess-Umgebungsvariablen übergeben **und** als `.env`-Datei geschrieben. `os.environ` funktioniert direkt ohne weitere Pakete.

### Nützliche Beispiele für "Weitere Vars"

| Schlüssel | Beispielwert | Zweck |
|---|---|---|
| `EMAIL_HOST` | `smtp.gmail.com` | E-Mail-Server |
| `EMAIL_PORT` | `587` | E-Mail-Port |
| `EMAIL_HOST_USER` | `dein@email.de` | E-Mail-Login |
| `EMAIL_HOST_PASSWORD` | `app-passwort` | E-Mail-Passwort |
| `EMAIL_USE_TLS` | `True` | TLS aktivieren |
| `CORS_ALLOW_ALL_ORIGINS` | `True` | CORS für API-Backends |
| `STRIPE_SECRET_KEY` | `sk_test_...` | Zahlungsanbieter |
| `AWS_ACCESS_KEY_ID` | `AKIA...` | AWS-Zugang |

---

## App verwalten

Jede App-Karte zeigt:

| Element | Bedeutung |
|---|---|
| **●** grün | App läuft |
| **○** rot | App gestoppt |
| 🐙 GitHub | Quelle ist ein Git-Repository |
| ⎇ Branch · Repo | Branch-Name und Repository-Kurzname |

### Aktionen

| Button | Aktion |
|---|---|
| **▶ Start** | PostgreSQL starten (ggf. initdb + Migrationen), Django runserver starten, Browser öffnen |
| **⏹ Stop** | Django und zugehörigen PostgreSQL-Server stoppen |
| **🌐** | Browser auf `http://localhost:<Port>` öffnen |
| **⬆ Update** | Neueste Version aus GitHub holen (`git pull`), Migrationen ausführen – App muss dafür gestoppt sein |
| **✏** | Konfiguration bearbeiten |
| **🗑** | App aus der Liste entfernen (Quellcode und Datenbankdaten bleiben erhalten) |

---

## Ersteinrichtung einer neuen App

Beim ersten Start einer App wird automatisch ausgeführt:

1. `initdb` – PostgreSQL-Datenbank initialisieren
2. Datenbankbenutzer und Datenbank anlegen
3. `manage.py migrate --noinput` – Django-Migrationen anwenden
4. `manage.py collectstatic --noinput` – Statische Dateien sammeln

Danach öffnet sich der Browser automatisch.

> **Django Superuser anlegen:** Terminal öffnen und
> `python manage.py createsuperuser` im App-Verzeichnis ausführen.

---

## GitHub / Git – Authentifizierung

### HTTPS

Keine weitere Konfiguration nötig. Für private Repositories kann Git nach einem Token fragen – dieser wird vom System-Git-Credential-Manager gespeichert.

### SSH mit eigenem Schlüssel

#### Option A – Schlüssel direkt im Tool erstellen (empfohlen)

Im App-Dialog neben dem SSH-Feld auf **🔑** (pinker Button) klicken:

| Schritt | Was passiert |
|---|---|
| Schlüsselname und Speicherort wählen | Standard: `~\.ssh\id_ed25519_<appname>` |
| **🔑 Schlüsselpaar erstellen** klicken | Generiert Ed25519-Keypair via `ssh-keygen` |
| **📋 Kopieren** | Public Key in die Zwischenablage |
| **⬇ .pub speichern** | Public-Key-Datei exportieren (z. B. auf den Desktop) |
| **🌐 GitHub öffnen** | Öffnet `github.com/settings/ssh/new` direkt im Browser |
| **Übernehmen & Schließen** | Privater Schlüsselpfad wird automatisch ins SSH-Feld eingetragen |

> **Public Key** → bei GitHub eintragen (öffentlich, kein Geheimnis)
> **Private Key** → bleibt lokal auf deinem PC – niemals hochladen oder teilen!

#### Option B – Bestehenden Schlüssel verwenden

1. SSH-Schlüsselpaar generieren (falls noch nicht vorhanden):
   ```powershell
   ssh-keygen -t ed25519 -C "deploy@meinserver"
   ```
2. Öffentlichen Schlüssel (`id_ed25519.pub`) bei GitHub unter
   **Settings → SSH and GPG keys → New SSH key** eintragen
3. Im App-Dialog auf **…** klicken und den Pfad zum **privaten** Schlüssel wählen

Das Tool übergibt den Schlüssel über `GIT_SSH_COMMAND` – die globale SSH-Konfiguration bleibt unberührt.

---

## Datenbank-Konfiguration

Jede App bekommt eine eigene PostgreSQL-Datenbank auf dem **Port 5433** (Standard, anpassbar). Die Daten liegen unter `data\app_<id>\`.

Das Tool setzt beim Start alle nötigen Variablen – als Prozess-Umgebungsvariablen **und** als `.env`-Datei im Quellverzeichnis. Siehe Abschnitt [Umgebungsvariablen & .env-Datei](#umgebungsvariablen--env-datei) für Details und Konfigurationsbeispiele.

---

## Voraussetzungen

### Entwicklungsrechner (Build)
- Python 3.11 oder neuer
- `pip install customtkinter pyinstaller`
- Git für Windows (für GitHub-Integration)

### Ziel-Windows-PC (Laufzeit)
- Windows 10 / 11 (64-Bit)
- Keine Installation erforderlich (alles portabel)
- Git für Windows empfohlen für GitHub-Integration:
  [git-scm.com/download/win](https://git-scm.com/download/win)

---

## Abhängigkeiten

| Paket | Zweck |
|---|---|
| `customtkinter` | Moderne grafische Oberfläche (Dark-Theme) |
| `pyinstaller` | EXE-Erstellung |

Python-Standardbibliotheken: `tkinter`, `sqlite3`, `subprocess`, `threading`, `pathlib`

---

## Portabler Betrieb (USB / Netzlaufwerk)

Den kompletten Ordner (`PortableDjangoManager\`) auf USB-Stick oder Netzlaufwerk kopieren. Auf dem Ziel-PC einfach `PortableDjangoManager.exe` starten.

Die App-Datenbanken in `data\` und Git-Klone in `repos\` bleiben dabei erhalten.

**Hinweis:** Auf dem Ziel-PC keine PostgreSQL-Installation nötig – das portable PostgreSQL in `postgres\` wird direkt genutzt.

---

## Troubleshooting

### PowerShell: „not digitally signed"

**Fehlermeldung:**
```
File .\setup_environment.ps1 cannot be loaded. The file is not digitally signed.
```

**Ursache:** Windows setzt beim Herunterladen oder Kopieren von Dateien aus dem Internet (GitHub-Download, USB-Stick, E-Mail-Anhang) einen unsichtbaren „Zone 3"-Marker (NTFS Alternate Data Stream). `RemoteSigned` blockiert damit alle unsignierten Skripte.

**Lösung 1 – Datei entsperren (einmalig, dauerhaft):**
```powershell
Unblock-File -Path .\setup_environment.ps1
.\setup_environment.ps1
```

**Lösung 2 – Einmalig mit Bypass starten:**
```powershell
powershell -ExecutionPolicy Bypass -File .\setup_environment.ps1
```

**Alle `.ps1`-Dateien im Ordner auf einmal entsperren:**
```powershell
Get-ChildItem C:\portable -Filter *.ps1 | Unblock-File
```

> `Unblock-File` löscht nur den Internet-Marker – es werden keine Sicherheitseinstellungen dauerhaft verändert.

---

### PowerShell: ExecutionPolicy setzen

Falls noch keine Ausführungsrichtlinie gesetzt wurde:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Mit `[A] Yes to All` bestätigen. Danach `Unblock-File` wie oben ausführen.

---

### ssh-keygen nicht gefunden

Der SSH-Key-Manager im Tool ruft `ssh-keygen` auf. Dieses ist seit Windows 10 (Version 1809) als optionales Feature enthalten.

**Prüfen:**
```powershell
ssh-keygen --version
```

**Nachinstallieren (als Admin):**
```powershell
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

---

## Sicherheitshinweis

Dieses Tool ist für **lokale Entwicklung und interne Tests** ausgelegt:

- PostgreSQL hört nur auf `127.0.0.1` (kein Netzwerkzugriff)
- Django läuft im `DEBUG=True`-Modus
- Nicht für produktiven oder öffentlich erreichbaren Betrieb geeignet

Für Produktionsdeployments → Linux-Server mit Nginx + Gunicorn verwenden.
