"""
runner.py  –  Prozess-Manager für Django + portables PostgreSQL
Ein einziger geteilter PostgreSQL-Server für alle Apps (SharedPostgresServer).
Jede App erhält automatisch ihren eigenen DB-Benutzer + Datenbank.
"""

import json
import os
import shutil
import socket
import subprocess

# Kein sichtbares Konsolenfenster auf Windows
_NO_WIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
import sys
import threading
import time
from pathlib import Path

# Wenn als PyInstaller-.exe gefroren: BASE_DIR = Ordner der .exe (portabler Ordner)
# Im Entwicklungs-Modus:             BASE_DIR = Ordner dieser Datei
BASE_DIR = (
    Path(sys.executable).parent
    if getattr(sys, "frozen", False)
    else Path(__file__).parent
)


# ─── Geteilter PostgreSQL-Server ──────────────────────────────────────────────

class SharedPostgresServer:
    """
    Ein einziger PostgreSQL-Prozess für alle Apps.
    Wird beim Programmstart gestartet und beim Beenden gestoppt.
    Jede App bekommt ihren eigenen User + DB (create_user_and_db / drop_user_and_db).
    """

    DEFAULT_PORT = 5432

    def __init__(self, base_dir: Path, port: int = DEFAULT_PORT, log_callback=None):
        self.base_dir     = Path(base_dir)
        self.port         = port
        self._log         = log_callback or print

        self.postgres_dir = self.base_dir / "postgres"
        self.data_dir     = self.base_dir / "pgdata"
        self.log_dir      = self.base_dir / "logs"

        if sys.platform == "win32":
            bin_sub       = self.postgres_dir / "bin"
            self._pg_bin  = bin_sub if bin_sub.is_dir() else self.postgres_dir
        else:
            self._pg_bin  = Path("/usr/bin")

        ext = ".exe" if sys.platform == "win32" else ""
        self._initdb    = self._pg_bin / f"initdb{ext}"
        self._pg_ctl    = self._pg_bin / f"pg_ctl{ext}"
        self._psql      = self._pg_bin / f"psql{ext}"
        self._pg_isready= self._pg_bin / f"pg_isready{ext}"

    # ── Umgebung ──────────────────────────────────────────────────────────

    def _pg_env(self) -> dict:
        env = os.environ.copy()
        pg_lib = self.postgres_dir / "lib"
        paths = [str(self._pg_bin)]
        if pg_lib.exists():
            paths.append(str(pg_lib))
        env["PATH"] = os.pathsep.join(paths) + os.pathsep + env.get("PATH", "")
        # UTC erzwingen: portables PostgreSQL hat kein share/timezone-Verzeichnis.
        # initdb/postgres würden sonst die Windows-Systemzeitzone (z.B. Europe/Berlin)
        # übernehmen und mit FATAL starten, weil die Zeitzonendateien fehlen.
        # UTC ist in PostgreSQL fest eingebaut – kein Dateisystem-Lookup nötig.
        env["TZ"] = "UTC"
        env["PGTZ"] = "UTC"
        return env

    # ── Status ────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        """Prüft ob PostgreSQL bereit für Verbindungen ist (pg_isready)."""
        r = subprocess.run(
            [str(self._pg_isready), "-h", "127.0.0.1", "-p", str(self.port)],
            capture_output=True, env=self._pg_env(), creationflags=_NO_WIN,
        )
        return r.returncode == 0

    # ── Initialisierung ───────────────────────────────────────────────────

    def init_if_needed(self) -> bool:
        """Führt initdb aus wenn der Datenbankcluster noch nicht existiert."""
        if (self.data_dir / "PG_VERSION").exists():
            return True  # Bereits initialisiert

        # Unvollständiges Verzeichnis aufräumen
        if self.data_dir.exists() and any(self.data_dir.iterdir()):
            self._log("  [PostgreSQL] Räume unvollständiges Datenbankverzeichnis auf …")
            shutil.rmtree(self.data_dir)

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self._log(f"  [PostgreSQL] Initialisiere gemeinsamen Datenbankserver …")
        pg_share = self.postgres_dir / "share"
        cmd = [
            str(self._initdb),
            "-D", str(self.data_dir),
            "-U", "postgres",
            "-E", "UTF8",
            "--no-locale",
            "--auth=trust",
        ]
        if pg_share.is_dir():
            cmd += ["-L", str(pg_share)]

        r = subprocess.run(
            cmd, capture_output=True, text=True,
            env=self._pg_env(), creationflags=_NO_WIN,
        )
        if r.returncode != 0:
            self._log(f"  [PostgreSQL] initdb FEHLER: {r.stderr.strip()[-500:]}")
            return False

        conf_path = self.data_dir / "postgresql.conf"
        with open(conf_path, "a", encoding="utf-8") as f:
            f.write(f"\nlisten_addresses = '127.0.0.1'\nport = {self.port}\n")

        self._log(f"  [PostgreSQL] Datenbankcluster initialisiert (Port {self.port}).")
        return True

    # ── Start / Stop ──────────────────────────────────────────────────────

    def start(self) -> bool:
        """Startet den geteilten PostgreSQL-Server. Gibt True zurück wenn bereit."""
        if self.is_running():
            return True

        if not self.init_if_needed():
            return False

        self._log(f"  [PostgreSQL] Starte gemeinsamen Server (Port {self.port}) …")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.log_dir / "postgres_shared.log"

        r = subprocess.run(
            [str(self._pg_ctl), "start",
             "-D", str(self.data_dir),
             "-l", str(log_file),
             "-w", "-t", "30"],
            capture_output=True, text=True,
            env=self._pg_env(), creationflags=_NO_WIN,
        )
        if r.returncode != 0:
            self._log(f"  [PostgreSQL] Startfehler: {r.stderr.strip() or '(kein Output)'}")
            if log_file.exists():
                tail = log_file.read_text(encoding="utf-8", errors="replace")[-1200:]
                self._log(f"  postgres.log: {tail.strip()}")
            return False

        return self.wait_until_ready(timeout=15)

    def wait_until_ready(self, timeout: int = 30) -> bool:
        """Wartet bis PostgreSQL Verbindungen akzeptiert."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.is_running():
                return True
            time.sleep(0.5)
        self._log(f"  [PostgreSQL] Timeout: Server nicht bereit nach {timeout}s.")
        return False

    def stop(self):
        """Stoppt den geteilten PostgreSQL-Server."""
        if not self.is_running():
            return
        self._log("  [PostgreSQL] Stoppe gemeinsamen Server …")
        try:
            subprocess.run(
                [str(self._pg_ctl), "stop",
                 "-D", str(self.data_dir), "-m", "fast", "-w", "-t", "15"],
                capture_output=True, text=True,
                env=self._pg_env(), creationflags=_NO_WIN,
                timeout=20,
            )
        except subprocess.TimeoutExpired:
            self._log("  [PostgreSQL] Warnung: Stopp-Timeout.")

    # ── SQL-Hilfsmethoden ─────────────────────────────────────────────────

    def _run_sql(self, sql: str, dbname: str = "postgres") -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(self._psql),
             "-h", "127.0.0.1", "-p", str(self.port),
             "-U", "postgres", "-d", dbname,
             "-c", sql],
            capture_output=True, text=True,
            env=self._pg_env(), creationflags=_NO_WIN,
        )

    # ── DB-Verwaltung pro App ─────────────────────────────────────────────

    def create_user_and_db(self, db_user: str, db_password: str, db_name: str) -> bool:
        """Legt DB-Benutzer und Datenbank an (idempotent – safe bei Wiederholung)."""
        # Benutzer anlegen (IF NOT EXISTS via DO $$)
        r = self._run_sql(
            f"DO $$ BEGIN "
            f"IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{db_user}') THEN "
            f"CREATE USER {db_user} WITH PASSWORD '{db_password}'; "
            f"END IF; END $$;"
        )
        if r.returncode != 0:
            self._log(f"  [PostgreSQL] Fehler bei CREATE USER '{db_user}': {r.stderr.strip()}")
            return False

        # Datenbank anlegen (prüfen ob sie schon existiert)
        check = subprocess.run(
            [str(self._psql),
             "-h", "127.0.0.1", "-p", str(self.port),
             "-U", "postgres",
             "-tAc", f"SELECT 1 FROM pg_database WHERE datname='{db_name}'"],
            capture_output=True, text=True,
            env=self._pg_env(), creationflags=_NO_WIN,
        )
        if "1" not in check.stdout:
            r = self._run_sql(
                f"CREATE DATABASE {db_name} OWNER {db_user} ENCODING 'UTF8';"
            )
            if r.returncode != 0:
                self._log(f"  [PostgreSQL] Fehler bei CREATE DATABASE '{db_name}': {r.stderr.strip()}")
                return False

        # Berechtigungen sicherstellen
        self._run_sql(
            f"GRANT ALL PRIVILEGES ON DATABASE {db_name} TO {db_user};"
        )
        return True

    def drop_user_and_db(self, db_user: str, db_name: str):
        """Löscht Datenbank und Benutzer einer App vollständig."""
        # Alle offenen Verbindungen trennen
        self._run_sql(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid();"
        )
        self._run_sql(f"DROP DATABASE IF EXISTS {db_name};")
        self._run_sql(f"DROP USER IF EXISTS {db_user};")
        self._log(f"  [PostgreSQL] Datenbank '{db_name}' und Benutzer '{db_user}' gelöscht.")

    def role_exists(self, db_user: str) -> bool:
        """Prüft ob ein DB-Benutzer bereits existiert."""
        r = subprocess.run(
            [str(self._psql),
             "-h", "127.0.0.1", "-p", str(self.port),
             "-U", "postgres",
             "-tAc", f"SELECT 1 FROM pg_roles WHERE rolname='{db_user}'"],
            capture_output=True, text=True,
            env=self._pg_env(), creationflags=_NO_WIN,
        )
        return r.returncode == 0 and "1" in r.stdout

    def check_binaries(self) -> str:
        """Gibt '' zurück wenn alles OK, sonst Fehlermeldung."""
        if sys.platform != "win32":
            return ""
        missing = []
        if not self._initdb.exists():
            missing.append(f"postgres\\bin\\initdb.exe  (erwartet: {self._initdb})")
        if missing:
            return (
                "Fehlende portable Komponenten im Programmordner:\n  • "
                + "\n  • ".join(missing)
                + f"\n\nProgrammordner: {self.base_dir}\n\n"
                "Bitte sicherstellen, dass der Ordner 'postgres'\n"
                "im selben Verzeichnis wie die .exe liegt."
            )
        return ""


# ─── App-Runner ───────────────────────────────────────────────────────────────

class AppRunner:
    """
    Verwaltet eine Django-Anwendung.
    PostgreSQL wird vom SharedPostgresServer verwaltet – dieser Runner
    startet/stoppt nur den Django-Prozess und richtet den eigenen DB-User ein.
    """

    # ─── Initialisierung ───────────────────────────────────────────────────

    def __init__(self, app: dict, pg_server: SharedPostgresServer,
                 base_dir: Path | None = None,
                 log_callback=None,
                 setup_done_callback=None):
        self.app      = app
        self.pg       = pg_server
        self.base_dir = Path(base_dir or BASE_DIR)
        self._ui_log  = log_callback or print
        self._setup_done_cb = setup_done_callback  # callable(app_id) → markiert setup_done=1

        self._log_file: "IO | None" = None
        self.log = self._log_both

        self._dj_proc: subprocess.Popen | None = None
        self._running = False
        self._lock = threading.Lock()

        # Verzeichnisse
        self.python_dir = self.base_dir / "python"
        self.log_dir    = self.base_dir / "logs"
        self.cache_dir  = self.base_dir / "cache"

        # postgres/lib für PATH (DLLs)
        self.postgres_dir = self.base_dir / "postgres"

        # Python-Executable
        if sys.platform == "win32":
            self._py = self.python_dir / "python.exe"
        else:
            self._py = Path(sys.executable)

        self._open_log_file()

    def _open_log_file(self):
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_path = self.log_dir / f"app_{self.app['id']}.log"
            self._log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        except Exception:
            self._log_file = None

    def _log_both(self, msg: str):
        self._ui_log(msg)
        if self._log_file:
            import datetime
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                self._log_file.write(f"[{ts}] {msg}\n")
            except Exception:
                pass

    # ─── Public API ────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        with self._lock:
            return (self._running
                    and self._dj_proc is not None
                    and self._dj_proc.poll() is None)

    def start(self, on_complete=None):
        """Startet Django in einem Hintergrundthread (PostgreSQL läuft bereits)."""
        t = threading.Thread(
            target=self._start_internal, args=(on_complete,), daemon=True
        )
        t.start()
        return t

    def stop(self):
        """Stoppt den Django-Prozess. PostgreSQL läuft weiter (vom SharedPostgresServer verwaltet)."""
        with self._lock:
            self._running = False
            if self._dj_proc and self._dj_proc.poll() is None:
                self._dj_proc.terminate()
                try:
                    self._dj_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._dj_proc.kill()
            self._dj_proc = None
        self.log(f"[{self.app['name']}] Gestoppt.")

    # ─── Interner Ablauf ───────────────────────────────────────────────────

    def check_portable_dirs(self) -> str:
        """Gibt '' zurück wenn alles OK, sonst eine Fehlermeldung."""
        missing = []
        if sys.platform == "win32":
            if not self._py.exists():
                missing.append(f"python\\python.exe  (erwartet: {self._py})")
        if missing:
            return (
                "Fehlende portable Komponenten im Programmordner:\n  • "
                + "\n  • ".join(missing)
                + f"\n\nProgrammordner: {self.base_dir}\n\n"
                "Bitte sicherstellen, dass der Ordner 'python'\n"
                "im selben Verzeichnis wie die .exe liegt."
            )
        return ""

    def _start_internal(self, on_complete=None):
        try:
            with self._lock:
                self._running = True

            # Portable-Verzeichnisse prüfen
            err = self.check_portable_dirs()
            if err:
                self.log(f"[{self.app['name']}] FEHLER: {err}")
                with self._lock:
                    self._running = False
                if on_complete:
                    on_complete(False)
                return

            # Port-Konflikt prüfen
            if not self._is_port_free(self.app["port"]):
                self.log(
                    f"[{self.app['name']}] FEHLER: Port {self.app['port']} ist bereits "
                    f"belegt. Bitte einen anderen Port konfigurieren."
                )
                with self._lock:
                    self._running = False
                if on_complete:
                    on_complete(False)
                return

            # Pakete installieren
            if not self._ensure_requirements():
                with self._lock:
                    self._running = False
                if on_complete:
                    on_complete(False)
                return

            # Abbruch falls stop() während pip aufgerufen wurde
            with self._lock:
                if not self._running:
                    return

            # PostgreSQL muss laufen (vom SharedPostgresServer)
            if not self.pg.is_running():
                self.log(f"[{self.app['name']}] FEHLER: PostgreSQL-Server läuft nicht. "
                         f"Bitte Programm neu starten.")
                with self._lock:
                    self._running = False
                if on_complete:
                    on_complete(False)
                return

            # Ersteinrichtung falls noch nicht erfolgt
            if self._setup_needed():
                self.log(f"[{self.app['name']}] Ersteinrichtung läuft …")
                if not self._setup():
                    with self._lock:
                        self._running = False
                    if on_complete:
                        on_complete(False)
                    return
                # setup_done in der DB markieren
                if self._setup_done_cb:
                    self._setup_done_cb(self.app["id"])
                self.app["setup_done"] = 1  # lokale Kopie aktualisieren

            # Abbruch falls stop() während Setup aufgerufen wurde
            with self._lock:
                if not self._running:
                    return

            # Django starten
            if not self._start_django():
                with self._lock:
                    self._running = False
                if on_complete:
                    on_complete(False)
                return

            self.log(
                f"[{self.app['name']}] Bereit → "
                f"http://localhost:{self.app['port']}"
            )
            if on_complete:
                on_complete(True)

            # Warten bis Django beendet wird
            self._dj_proc.wait()
            with self._lock:
                self._running = False
            self.log(f"[{self.app['name']}] Beendet.")

        except Exception as exc:
            self.log(f"[{self.app['name']}] FEHLER: {exc}")
            with self._lock:
                self._running = False
            if on_complete:
                on_complete(False)

    # ─── Setup ────────────────────────────────────────────────────────────

    def _setup_needed(self) -> bool:
        """True wenn DB-User/DB/Migrationen noch nicht eingerichtet wurden."""
        if self.app.get("setup_done", 0):
            return False
        # Zusätzlicher Check: falls setup_done=0 aber Role schon existiert → auch prüfen
        # (z.B. nach manuellem Eingriff). In dem Fall trotzdem Setup laufen lassen –
        # create_user_and_db ist idempotent.
        return True

    def _setup(self) -> bool:
        """Erstellt DB-User + Datenbank + führt Django-Migrationen aus."""
        self.log(f"  [{self.app['name']}] Erstelle Datenbankbenutzer und Datenbank …")
        ok = self.pg.create_user_and_db(
            self.app["db_user"],
            self.app["db_password"],
            self.app["db_name"],
        )
        if not ok:
            self.log(f"  [{self.app['name']}] Fehler bei der Datenbankeinrichtung.")
            return False

        self.log(f"  [{self.app['name']}] Django-Migrationen …")
        env = self._build_env()
        r = subprocess.run(
            [str(self._py), "manage.py", "migrate", "--noinput"],
            cwd=self.app["source_path"],
            env=env,
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            out = (r.stderr or r.stdout).strip()[-1000:]
            self.log(f"  Migrations-Fehler (returncode={r.returncode}): {out}")
            return False

        # Superuser automatisch anlegen
        su_user = self.app.get("su_username", "").strip()
        su_pass = self.app.get("su_password", "").strip()
        if su_user and su_pass:
            self.log(f"  [{self.app['name']}] Lege Superuser '{su_user}' an …")
            su_env = env.copy()
            su_env["DJANGO_SUPERUSER_PASSWORD"] = su_pass
            su_email = self.app.get("su_email", "admin@example.com").strip()
            r_su = subprocess.run(
                [str(self._py), "manage.py", "createsuperuser",
                 "--noinput",
                 f"--username={su_user}",
                 f"--email={su_email}"],
                cwd=self.app["source_path"],
                env=su_env,
                capture_output=True, text=True,
            )
            if r_su.returncode == 0:
                self.log(f"  [{self.app['name']}] Superuser '{su_user}' erstellt.")
            else:
                err = (r_su.stderr or r_su.stdout).strip()
                # "already exists" ist kein Fehler
                if "already exists" in err.lower():
                    self.log(f"  [{self.app['name']}] Superuser '{su_user}' existiert bereits.")
                else:
                    self.log(f"  [{self.app['name']}] Superuser-Warnung: {err[-300:]}")

        self.log(f"  [{self.app['name']}] Ersteinrichtung abgeschlossen.")
        return True

    # ─── Migrationen (für Update-Workflow) ────────────────────────────────

    def _run_migrations(self) -> bool:
        """
        Installiert Pakete + führt Django-Migrationen aus ohne den Server zu starten.
        PostgreSQL muss bereits laufen (SharedPostgresServer).
        """
        self._ensure_requirements()

        if not self.pg.is_running():
            self.log(f"  [{self.app['name']}] PostgreSQL nicht verfügbar für Migrationen.")
            return False

        env = self._build_env()
        r = subprocess.run(
            [str(self._py), "manage.py", "migrate", "--noinput"],
            cwd=self.app["source_path"],
            env=env,
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            out = (r.stderr or r.stdout).strip()[-1000:]
            self.log(f"  Migrations-Fehler (returncode={r.returncode}): {out}")
        else:
            self.log(f"  [{self.app['name']}] Migrationen OK.")

        self._run_collectstatic(env)

        return r.returncode == 0

    # ─── Requirements ─────────────────────────────────────────────────────

    def _ensure_requirements(self) -> bool:
        req_file = Path(self.app["source_path"]) / "requirements.txt"
        if not req_file.exists():
            return True

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        marker = self.cache_dir / f"app_{self.app['id']}_pip.done"
        try:
            if marker.exists() and marker.stat().st_mtime >= req_file.stat().st_mtime:
                return True
        except OSError:
            pass

        self.log(f"  [{self.app['name']}] Installiere Pakete (pip install -r requirements.txt) …")
        r = subprocess.run(
            [str(self._py), "-m", "pip", "install", "-r", str(req_file),
             "--quiet", "--no-warn-script-location"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            err = (r.stderr or r.stdout).strip()[-800:]
            self.log(f"  pip-Fehler: {err}")
            return False
        marker.touch()
        self.log(f"  [{self.app['name']}] Pakete installiert.")
        return True

    # ─── Superuser ────────────────────────────────────────────────────────

    def setup_done(self) -> bool:
        """True wenn Ersteinrichtung abgeschlossen wurde."""
        return bool(self.app.get("setup_done", 0))

    def create_superuser(
        self, username: str, email: str, password: str
    ) -> tuple[bool, str]:
        """
        Legt einen Django-Superuser an.
        PostgreSQL muss laufen (SharedPostgresServer).
        """
        if not self.pg.is_running():
            return False, "PostgreSQL-Server läuft nicht."

        env = self._build_env()
        env["DJANGO_SUPERUSER_PASSWORD"] = password

        r = subprocess.run(
            [str(self._py), "manage.py", "createsuperuser",
             "--noinput", f"--username={username}", f"--email={email}"],
            cwd=self.app["source_path"],
            env=env,
            capture_output=True, text=True,
        )

        if r.returncode == 0:
            return True, f"Superuser '{username}' wurde erfolgreich erstellt."
        err = (r.stderr or r.stdout).strip()
        return False, err or "Unbekannter Fehler beim Erstellen des Superusers."

    # ─── Hilfsmethoden ────────────────────────────────────────────────────

    def _is_port_free(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) != 0

    def _write_site_pathfix(self):
        if sys.platform != "win32":
            return
        site_pkgs = self.python_dir / "Lib" / "site-packages"
        if not site_pkgs.is_dir():
            return

        module_content = (
            "import os, sys\n"
            "_s = os.environ.get('DJANGO_SRC_PATH')\n"
            "if _s and _s not in sys.path:\n"
            "    sys.path.insert(0, _s)\n"
        )
        pth_content = "import _pdjango_pathfix\n"

        try:
            module_file = site_pkgs / "_pdjango_pathfix.py"
            if not module_file.exists() or module_file.read_text(encoding="utf-8") != module_content:
                module_file.write_text(module_content, encoding="utf-8")
            pth_file = site_pkgs / "_pdjango_pathfix.pth"
            if not pth_file.exists() or pth_file.read_text(encoding="utf-8") != pth_content:
                pth_file.write_text(pth_content, encoding="utf-8")
        except OSError:
            pass

    # ─── Django ───────────────────────────────────────────────────────────

    def _run_collectstatic(self, env: dict) -> None:
        """Collectstatic ausführen und Ausgabe in Log sichtbar machen."""
        self.log(f"  [{self.app['name']}] collectstatic …")
        r = subprocess.run(
            [str(self._py), "manage.py", "collectstatic", "--noinput"],
            cwd=self.app["source_path"],
            env=env,
            capture_output=True,
            text=True,
        )
        out = (r.stdout + r.stderr).strip()
        if out:
            # Nur letzte 800 Zeichen ausgeben (kann lang sein)
            for line in out[-800:].splitlines():
                self.log(f"  [{self.app['name']}] {line}")
        if r.returncode != 0:
            self.log(f"  [{self.app['name']}] collectstatic Warnung (returncode={r.returncode})")

    def _start_django(self) -> bool:
        self.log(f"  [{self.app['name']}] Starte Django (Port {self.app['port']}) …")
        env = self._build_env()
        self._write_dotenv(env)
        # Statische Dateien vor jedem Start sammeln (nicht nur beim Erstsetup),
        # damit manuell hinzugefügte Dateien (z.B. Logo) immer aktuell sind.
        self._run_collectstatic(env)
        with self._lock:
            self._dj_proc = subprocess.Popen(
                [str(self._py), "manage.py", "runserver",
                 "--insecure",          # statische Dateien aus STATIC_ROOT auch mit DEBUG=False
                 f"0.0.0.0:{self.app['port']}"],
                cwd=self.app["source_path"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        threading.Thread(target=self._pipe_output, daemon=True).start()
        time.sleep(2)
        with self._lock:
            return self._dj_proc.poll() is None

    def _pipe_output(self):
        if self._dj_proc and self._dj_proc.stdout:
            for line in self._dj_proc.stdout:
                self.log(f"  [{self.app['name']}] {line.rstrip()}")

    # ─── Umgebungsvariablen ───────────────────────────────────────────────

    def _build_env(self) -> dict:
        env = os.environ.copy()
        # Shared PostgreSQL-Port verwenden (nicht den veralteten per-app db_port)
        pg_port = str(self.pg.port)
        port = str(self.app.get("port", "8000"))
        env.update({
            "DB_NAME":   self.app["db_name"],
            "DB_USER":   self.app["db_user"],
            "DB_PASS":   self.app["db_password"],
            "DB_HOST":   "127.0.0.1",
            "DB_PORT":   pg_port,
            # DEBUG=False + --insecure: Django bedient statische Dateien aus
            # STATIC_ROOT (staticfiles/), genauso wie nginx in Produktion.
            # Mit DEBUG=True würden Finders genutzt (app/static/ + STATICFILES_DIRS),
            # aber STATIC_ROOT wird dabei NICHT durchsucht → Logo 404.
            "DEBUG":     "False",
            "ALLOWED_HOSTS": self.app.get("allowed_hosts", "localhost,127.0.0.1"),
            # CSRF_TRUSTED_ORIGINS für lokalen HTTP-Zugriff (nötig wenn DEBUG=False)
            "CSRF_TRUSTED_ORIGINS": f"http://localhost:{port},http://127.0.0.1:{port}",
            "DJANGO_SETTINGS_MODULE": self.app.get("settings_module", "core.settings"),
            "DATABASE_URL": (
                f"postgresql://{self.app['db_user']}:"
                f"{self.app['db_password']}@127.0.0.1:"
                f"{pg_port}/{self.app['db_name']}"
            ),
            "DB_ENGINE": "django.db.backends.postgresql",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        })
        sk = self.app.get("secret_key", "")
        if sk:
            env["SECRET_KEY"] = sk
        try:
            extra = json.loads(self.app.get("extra_env") or "{}")
            env.update({k: str(v) for k, v in extra.items() if k})
        except (json.JSONDecodeError, TypeError):
            pass
        src = self.app.get("source_path", "")
        if src:
            env["DJANGO_SRC_PATH"] = str(Path(src))
        self._write_site_pathfix()
        pg_lib = self.postgres_dir / "lib"
        if pg_lib.exists():
            path = env.get("PATH", "")
            env["PATH"] = f"{pg_lib}{os.pathsep}{path}"
        return env

    def _write_dotenv(self, env: dict):
        src = Path(self.app.get("source_path", ""))
        if not src.is_dir():
            return
        managed_keys = [
            "DEBUG", "SECRET_KEY", "ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS",
            "DJANGO_SETTINGS_MODULE",
            "DB_ENGINE", "DB_NAME", "DB_USER", "DB_PASS", "DB_HOST", "DB_PORT",
            "DATABASE_URL",
        ]
        try:
            extra_keys = list(json.loads(self.app.get("extra_env") or "{}").keys())
        except (json.JSONDecodeError, TypeError):
            extra_keys = []
        lines = []
        for k in managed_keys + extra_keys:
            if k in env:
                v = env[k]
                lines.append(f'{k}="{v}"\n' if ("," in v or " " in v) else f"{k}={v}\n")
        try:
            (src / ".env").write_text("".join(lines), encoding="utf-8")
            self.log(f"  [{self.app['name']}] .env aktualisiert.")
        except OSError as exc:
            self.log(f"  [{self.app['name']}] .env konnte nicht geschrieben werden: {exc}")
