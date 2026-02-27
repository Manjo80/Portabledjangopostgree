# Portable Django Manager

Ein grafisches Windows-Tool zum Betreiben mehrerer Django-Webanwendungen – ohne Installation, ohne Admin-Rechte, portabel auf USB-Stick oder Netzlaufwerk.

Mit nginx als Reverse-Proxy und waitress als WSGI-Server eignet sich das Tool nicht nur für die lokale Entwicklung, sondern auch als **kleiner interner Test- oder Demo-Server** im LAN.

---

## Was ist drin

| Komponente | Version | Zweck |
|---|---|---|
| **Python** (embedded) | 3.12 | Django-Laufzeit – kein System-Python nötig |
| **PostgreSQL** (portabel) | 16 | Datenbank – keine Installation nötig |
| **nginx** (portabel) | 1.26.3 | Reverse-Proxy: static/media direkt, Django dynamisch |
| **waitress** (pip) | aktuell | Produktionsreifer WSGI-Server (multi-threaded) |
| **customtkinter** | – | Grafische Oberfläche (Dark-Theme) |

---

## Schnellstart

### 1. Umgebung einrichten (einmalig)

```powershell
# Skript entsperren (einmalig nach Download / USB-Kopie)
Unblock-File -Path .\setup_environment.ps1

# Ausführen – lädt Python + PostgreSQL + nginx herunter
.\setup_environment.ps1
```

Das Skript lädt herunter und richtet ein:
- `python\` – eingebettetes Python 3.12 (~30 MB)
- `postgres\` – portables PostgreSQL 16 (~300 MB)
- `nginx\nginx-1.26.3\` – portables nginx (~1.5 MB)

> **PowerShell-Fehler „not digitally signed"?**
> ```powershell
> powershell -ExecutionPolicy Bypass -File .\setup_environment.ps1
> ```
> Alle `.ps1`-Dateien auf einmal entsperren:
> ```powershell
> Get-ChildItem C:\portable -Filter *.ps1 | Unblock-File
> ```

#### Setup-Optionen

```powershell
# nginx-Download überspringen (nicht benötigt)
.\setup_environment.ps1 -SkipNginxDownload

# PostgreSQL-Download überspringen (ZIP muss als postgresql-binaries.zip vorliegen)
.\setup_environment.ps1 -SkipPostgresDownload

# Andere Versionen
.\setup_environment.ps1 -NginxVersion "1.27.0"
```

---

### 2. Tool starten

```cmd
# Direkt mit Python (Entwicklung)
python main.py

# Als EXE
PortableDjangoManager.exe
```

---

### 3. EXE erstellen

```cmd
build_exe.bat
```

Erzeugt `dist\PortableDjangoManager.exe` via PyInstaller. Die EXE läuft auf jedem Windows 10/11 (64-Bit) ohne Python-Installation – `python\`, `postgres\` und `nginx\` müssen daneben liegen.

---

## Verzeichnisstruktur

```
PortableDjangoManager\
│
├── PortableDjangoManager.exe   ← Hauptprogramm (nach build_exe.bat)
├── main.py                     ← Hauptprogramm (Quellcode)
├── db.py                       ← SQLite-Konfigurationsspeicher
├── runner.py                   ← Prozess-Manager (Django + PostgreSQL + nginx)
├── nginx_manager.py            ← nginx-Wrapper (Config, Start/Stop, Download)
├── git_manager.py              ← Git-Integration (Clone / Pull / SSH)
├── requirements.txt            ← Python-Abhängigkeiten
├── build_exe.bat               ← EXE-Builder (PyInstaller)
├── setup_environment.ps1       ← Setup: Python + PostgreSQL + nginx
│
├── python\                     ← Eingebettetes Python 3.12 (nach Setup)
├── postgres\                   ← Portables PostgreSQL 16 (nach Setup)
├── nginx\                      ← Portables nginx 1.26.3 (nach Setup)
│   └── nginx-1.26.3\
│       ├── nginx.exe
│       └── conf\mime.types
│
├── apps.db                     ← SQLite mit App-Konfigurationen (auto)
├── repos\                      ← Lokale Git-Klone (auto bei GitHub-Apps)
├── data\                       ← PostgreSQL-Datenbankdaten (auto)
└── logs\                       ← Logdateien (auto)
```

---

## App hinzufügen

Im Hauptfenster auf **＋ App hinzufügen** klicken.

### Quelle: Lokaler Ordner

Beliebiges Django-Projektverzeichnis wählen. Muss eine `manage.py` enthalten.

### Quelle: GitHub / Git-Repository

| Feld | Beschreibung |
|---|---|
| **Repository-URL** | HTTPS: `https://github.com/user/repo`<br>SSH: `git@github.com:user/repo.git` |
| **Branch** | z. B. `main` oder `develop` |
| **SSH-Schlüssel** *(optional)* | Privater Schlüssel; leer lassen für HTTPS |

Beim Speichern wird das Repository sofort geklont.

---

## nginx-Konfiguration

Im App-Dialog gibt es die Sektion **nginx (optionaler Reverse-Proxy)**.

| Einstellung | Standard | Bedeutung |
|---|---|---|
| **nginx aktivieren** | aus | nginx als Reverse-Proxy vor Django schalten |
| **nginx-Port** | `80` | Außen-Port (User greift hier drauf zu) |

### Was nginx übernimmt

```
Browser → nginx :80
  ├── /static/*  →  staticfiles/ direkt (kein Django-Overhead)
  ├── /media/*   →  media/ direkt
  └── /*         →  proxy_pass → waitress :8000 (Django)
```

- Statische Dateien werden von nginx direkt ausgeliefert, mit `Cache-Control: public, max-age=7d`
- Django bekommt **nur noch dynamische Requests**
- Ohne nginx: Django-Runserver mit `--insecure` (Entwicklungsmodus)

### nginx + waitress = Test-Server-Modus

Wenn nginx aktiviert ist, startet der Runner automatisch **waitress** statt `manage.py runserver`:

| | runserver (ohne nginx) | waitress + nginx |
|---|---|---|
| Requests gleichzeitig | 1 (single-thread) | 8 Threads |
| Static files | Django (langsam) | nginx (schnell) |
| Geeignet für | Lokale Entwicklung | Interner Test-Server |
| WSGI-Standard | ✗ (Dev-only) | ✅ |

waitress wird beim ersten Start automatisch via pip installiert.

---

## Fehlende statische Dateien (z. B. Logo)

Dateien die nicht im Git-Repository der App sind (z. B. ein Logo), können dauerhaft bereitgestellt werden ohne das Repo zu ändern:

1. Ordner `_portable_static/` im App-Quellverzeichnis anlegen
2. Dateien dort ablegen, z. B. `_portable_static/img/logo.png`
3. Bei jedem App-Start werden sie automatisch nach `staticfiles/` kopiert

```
meine_app\
├── manage.py
├── staticfiles\         ← wird automatisch befüllt
└── _portable_static\    ← hier eigene Dateien ablegen
    └── img\
        └── logo.png
```

---

## Auto-Restart

Wenn Django oder waitress unerwartet abstürzt (nicht durch manuellen Stop), wird der Prozess automatisch neu gestartet – bis zu **5 Mal**, mit 5 Sekunden Pause. Im Log erscheint:

```
[meine_app] ⚠ Prozess unerwartet beendet – Neustart 1/5 in 5 s …
[meine_app] ✅ Neustart 1 erfolgreich.
```

---

## Umgebungsvariablen & .env-Datei

Im App-Dialog → Abschnitt **Umgebungsvariablen**:

| Feld | Standard | Bedeutung |
|---|---|---|
| **Settings-Modul** | `core.settings` | `DJANGO_SETTINGS_MODULE` |
| **Allowed Hosts** | `localhost,127.0.0.1` | Für LAN-Zugriff: IP des Rechners eintragen |
| **SECRET_KEY** | *(leer)* | Überschreibt den Key aus `settings.py` (⟳ = sicher zufällig) |
| **Weitere Vars** | – | Beliebige KEY=VALUE-Paare |

### Generierte .env-Datei

Beim Start wird automatisch eine `.env` ins App-Quellverzeichnis geschrieben:

```env
DEBUG="False"
ALLOWED_HOSTS="localhost,127.0.0.1"
DJANGO_SETTINGS_MODULE=core.settings
DB_NAME=meine_app
DB_USER=meine_app
DB_PASS=<generiertes-passwort>
DB_HOST=127.0.0.1
DB_PORT=5433
DATABASE_URL="postgresql://meine_app:passwort@127.0.0.1:5433/meine_app"
SECRET_KEY=<sicherer-zufallsschlüssel>
```

> Hinweis: `DEBUG=False` ist Standard. Django läuft im Produktionsmodus.

### settings.py anpassen

**python-decouple** (`pip install python-decouple`):

```python
from decouple import config

SECRET_KEY    = config("SECRET_KEY", default="dev-only-insecure-key")
DEBUG         = config("DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost").split(",")

DATABASES = {
    "default": {
        "ENGINE":   "django.db.backends.postgresql",
        "NAME":     config("DB_NAME"),
        "USER":     config("DB_USER"),
        "PASSWORD": config("DB_PASS"),
        "HOST":     config("DB_HOST", default="127.0.0.1"),
        "PORT":     config("DB_PORT", default="5432"),
    }
}
```

**os.environ** (ohne externe Abhängigkeit):

```python
import os

SECRET_KEY    = os.environ.get("SECRET_KEY", "dev-only-insecure-key")
DEBUG         = os.environ.get("DEBUG", "False") == "True"
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

### Nützliche Weitere Vars

| Schlüssel | Beispielwert | Zweck |
|---|---|---|
| `EMAIL_HOST` | `smtp.gmail.com` | E-Mail-Server |
| `EMAIL_PORT` | `587` | E-Mail-Port |
| `EMAIL_HOST_USER` | `dein@email.de` | E-Mail-Login |
| `EMAIL_HOST_PASSWORD` | `app-passwort` | E-Mail-Passwort |
| `EMAIL_USE_TLS` | `True` | TLS aktivieren |
| `CORS_ALLOW_ALL_ORIGINS` | `True` | CORS für API-Backends |

---

## App verwalten

### App-Karte

| Element | Bedeutung |
|---|---|
| **●** grün | App läuft |
| **○** rot | App gestoppt |
| 🐙 GitHub | Quelle ist ein Git-Repository |
| `nginx :80 → Django :8000` | nginx-Modus aktiv |

### Aktionen

| Button | Aktion |
|---|---|
| **▶ Start** | PostgreSQL starten, Django + nginx starten, Browser öffnen |
| **⏹ Stop** | Django, waitress und nginx stoppen |
| **🌐** | Browser öffnen (nginx-Port wenn aktiv, sonst App-Port) |
| **⬆ Update** | `git pull` + Migrationen ausführen (App muss gestoppt sein) |
| **👤** | Django-Superuser anlegen (GUI-Dialog) |
| **🗄** | Datenbank zurücksetzen (Migrationen neu ausführen) |
| **✏** | Konfiguration bearbeiten |
| **🗑** | App entfernen (Quellcode bleibt erhalten) |

---

## Ersteinrichtung einer neuen App

Beim ersten Start läuft automatisch:

1. PostgreSQL `initdb` – Datenbankcluster initialisieren
2. DB-Benutzer und Datenbank anlegen
3. `manage.py migrate --noinput` – Migrationen anwenden
4. `manage.py collectstatic --noinput` – Statische Dateien sammeln
5. Superuser anlegen (falls im Dialog konfiguriert)

---

## Als interner Test-Server nutzen

Um die App im LAN erreichbar zu machen (z. B. für Kollegen oder Mobilgeräte):

1. **Allowed Hosts** im App-Dialog ergänzen:
   ```
   localhost,127.0.0.1,192.168.1.50
   ```
   (IP des Windows-Rechners eintragen)

2. **nginx aktivieren** und nginx-Port auf `80` lassen

3. **Windows-Firewall**: Port 80 freigeben (als Admin):
   ```powershell
   New-NetFirewallRule -DisplayName "nginx Port 80" -Direction Inbound `
     -Protocol TCP -LocalPort 80 -Action Allow
   ```

4. App starten → im LAN erreichbar unter `http://192.168.1.50/`

> **Nicht geeignet für:** Öffentliches Internet, produktive Kundendaten, HTTPS-Pflicht.
> Für echten Produktionsbetrieb → Linux-Server mit nginx + gunicorn + Let's Encrypt.

---

## GitHub / Git – Authentifizierung

### HTTPS

Keine weitere Konfiguration nötig.

### SSH

Im App-Dialog neben dem SSH-Feld auf **🔑** klicken:

| Schritt | Was passiert |
|---|---|
| **🔑 Schlüsselpaar erstellen** | Generiert Ed25519-Keypair via `ssh-keygen` |
| **📋 Kopieren** | Public Key in Zwischenablage |
| **🌐 GitHub öffnen** | Öffnet `github.com/settings/ssh/new` |

Privaten Schlüsselpfad einfach ins SSH-Feld eintragen oder per **…** wählen.

---

## Voraussetzungen

### Build-Rechner
- Python 3.11+, `pip install customtkinter pyinstaller`
- Git für Windows (für GitHub-Integration)

### Ziel-Windows-PC
- Windows 10 / 11 (64-Bit)
- Keine Installation erforderlich (alles portabel)
- Git für Windows empfohlen: [git-scm.com/download/win](https://git-scm.com/download/win)

---

## Troubleshooting

### PowerShell: „not digitally signed"

```powershell
Unblock-File -Path .\setup_environment.ps1
# oder einmalig:
powershell -ExecutionPolicy Bypass -File .\setup_environment.ps1
```

### „pyinstaller is not recognized"

```cmd
python -m PyInstaller --onefile --windowed --name PortableDjangoManager main.py
```

### nginx startet nicht

- Prüfen ob `nginx\nginx-1.26.3\nginx.exe` vorhanden (ggf. Setup neu ausführen)
- Prüfen ob Port 80 bereits belegt: `netstat -ano | findstr :80`
- Anderen nginx-Port im App-Dialog konfigurieren (z. B. 8080)
- nginx-Logs unter `nginx\logs\error_<app>.log` prüfen

### Logo oder statische Datei fehlt (404)

Die Datei ist nicht im Git-Repository der App. Lösung:

```
<App-Quellverzeichnis>\_portable_static\img\logo.png
```

→ Wird beim nächsten Start automatisch nach `staticfiles\img\logo.png` kopiert.

### ssh-keygen nicht gefunden

```powershell
# Prüfen
ssh-keygen --version

# Nachinstallieren (als Admin)
Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0
```

---

## Sicherheitshinweis

Das Tool läuft mit `DEBUG=False` und einem sicheren `SECRET_KEY`.

**Geeignet für:**
- Lokale Entwicklung
- Interne Demos und Tests im LAN
- Präsentationen und Schulungen

**Nicht geeignet für:**
- Öffentliches Internet (kein HTTPS, kein DDoS-Schutz)
- Produktiven Betrieb mit echten Kundendaten
- Hochlast (waitress/nginx skalieren nicht auf viele gleichzeitige User)

PostgreSQL hört nur auf `127.0.0.1` – kein direkter Netzwerkzugriff auf die Datenbank.
