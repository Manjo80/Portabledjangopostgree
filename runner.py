"""
runner.py  –  Prozess-Manager für Django + portables PostgreSQL
Startet/stoppt für jede App eine eigene PostgreSQL-Datenbank und
einen Django-Entwicklungsserver.
"""

import json
import os
import socket
import subprocess
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


class AppRunner:
    """Verwaltet eine Django-Anwendung mit zugehörigem PostgreSQL."""

    # ─── Initialisierung ───────────────────────────────────────────────────

    def __init__(self, app: dict, base_dir: Path | None = None,
                 log_callback=None):
        self.app = app
        self.base_dir = Path(base_dir or BASE_DIR)
        self.log = log_callback or print

        self._pg_proc: subprocess.Popen | None = None
        self._dj_proc: subprocess.Popen | None = None
        self._running = False
        self._lock = threading.Lock()

        # Verzeichnisse
        self.python_dir  = self.base_dir / "python"
        self.postgres_dir = self.base_dir / "postgres"
        self.data_dir    = self.base_dir / "data" / f"app_{app['id']}"
        self.log_dir     = self.base_dir / "logs"

        # Executables (Windows vs. Linux für Entwicklung)
        if sys.platform == "win32":
            self._py      = self.python_dir / "python.exe"
            self._pg_bin  = self.postgres_dir / "bin"
        else:
            self._py      = Path(sys.executable)
            self._pg_bin  = Path("/usr/bin")

        self._initdb    = self._pg_bin / ("initdb.exe"    if sys.platform == "win32" else "initdb")
        self._pg_ctl    = self._pg_bin / ("pg_ctl.exe"    if sys.platform == "win32" else "pg_ctl")
        self._psql      = self._pg_bin / ("psql.exe"      if sys.platform == "win32" else "psql")
        self._pg_isready= self._pg_bin / ("pg_isready.exe"if sys.platform == "win32" else "pg_isready")

    # ─── Public API ────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        with self._lock:
            return (self._running
                    and self._dj_proc is not None
                    and self._dj_proc.poll() is None)

    def start(self, on_complete=None):
        """Startet PostgreSQL + Django in einem Hintergrundthread."""
        t = threading.Thread(
            target=self._start_internal, args=(on_complete,), daemon=True
        )
        t.start()
        return t

    def stop(self):
        """Stoppt Django und PostgreSQL."""
        with self._lock:
            self._running = False
            if self._dj_proc and self._dj_proc.poll() is None:
                self._dj_proc.terminate()
                try:
                    self._dj_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._dj_proc.kill()
            self._dj_proc = None
        self._stop_postgres()
        self.log(f"[{self.app['name']}] Gestoppt.")

    # ─── Interner Ablauf ───────────────────────────────────────────────────

    def check_portable_dirs(self) -> str:
        """Gibt '' zurück wenn alles OK, sonst eine Fehlermeldung."""
        missing = []
        if sys.platform == "win32":
            if not self._py.exists():
                missing.append(f"python\\python.exe  (erwartet: {self._py})")
            if not self._initdb.exists():
                missing.append(f"postgres\\bin\\initdb.exe  (erwartet: {self._initdb})")
        if missing:
            return (
                "Fehlende portable Komponenten im Programmordner:\n  • "
                + "\n  • ".join(missing)
                + f"\n\nProgrammordner: {self.base_dir}\n\n"
                "Bitte sicherstellen, dass die Ordner 'python' und 'postgres'\n"
                "im selben Verzeichnis wie die .exe liegen."
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

            # Port-Konflikt prüfen bevor irgendetwas gestartet wird
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

            if self._setup_needed():
                self.log(f"[{self.app['name']}] Ersteinrichtung läuft …")
                if not self._setup():
                    with self._lock:
                        self._running = False
                    if on_complete:
                        on_complete(False)
                    return

            if not self._start_postgres():
                with self._lock:
                    self._running = False
                if on_complete:
                    on_complete(False)
                return

            if not self._start_django():
                self._stop_postgres()
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
            self._stop_postgres()
            self.log(f"[{self.app['name']}] Beendet.")

        except Exception as exc:
            self.log(f"[{self.app['name']}] FEHLER: {exc}")
            with self._lock:
                self._running = False
            if on_complete:
                on_complete(False)

    # ─── PostgreSQL ────────────────────────────────────────────────────────

    def _setup_needed(self) -> bool:
        return not (self.data_dir / "PG_VERSION").exists()

    def _setup(self) -> bool:
        """initdb + Datenbank anlegen + Django-Migrationen."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.log(f"  [{self.app['name']}] Initialisiere Datenbank …")
        r = subprocess.run(
            [str(self._initdb), "-D", str(self.data_dir),
             "-U", "postgres", "-E", "UTF8", "--no-locale", "--auth=trust"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            self.log(f"  initdb-Fehler: {r.stderr}")
            return False

        # Minimal-Konfiguration anhängen
        with open(self.data_dir / "postgresql.conf", "a", encoding="utf-8") as f:
            f.write(
                f"\nlisten_addresses = '127.0.0.1'\n"
                f"port = {self.app['db_port']}\n"
            )

        if not self._start_postgres(wait=True):
            return False

        if not self._install_requirements():
            self._stop_postgres()
            return False

        self.log(f"  [{self.app['name']}] Erstelle Datenbankbenutzer …")
        self._psql_exec(
            f"CREATE USER {self.app['db_user']} WITH PASSWORD "
            f"'{self.app['db_password']}';"
        )
        self._psql_exec(
            f"CREATE DATABASE {self.app['db_name']} "
            f"OWNER {self.app['db_user']} ENCODING 'UTF8';"
        )
        self._psql_exec(
            f"GRANT ALL PRIVILEGES ON DATABASE "
            f"{self.app['db_name']} TO {self.app['db_user']};"
        )

        self.log(f"  [{self.app['name']}] Django-Migrationen …")
        env = self._build_env()
        r = subprocess.run(
            [str(self._py), "manage.py", "migrate", "--noinput"],
            cwd=self.app["source_path"],
            env=env,
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            self.log(f"  Migrations-Fehler: {r.stderr}")
            self._stop_postgres()
            return False

        # Statische Dateien sammeln (Fehler ignorieren – nicht kritisch)
        subprocess.run(
            [str(self._py), "manage.py", "collectstatic", "--noinput"],
            cwd=self.app["source_path"],
            env=env,
            capture_output=True,
        )

        self._stop_postgres()
        self.log(f"  [{self.app['name']}] Ersteinrichtung abgeschlossen.")
        return True

    def _start_postgres(self, wait: bool = False) -> bool:
        self.log(
            f"  [{self.app['name']}] Starte PostgreSQL "
            f"(Port {self.app['db_port']}) …"
        )
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = self.log_dir / f"postgres_{self.app['id']}.log"

        r = subprocess.run(
            [str(self._pg_ctl), "start",
             "-D", str(self.data_dir),
             "-l", str(log_file),
             "-w", "-t", "30"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            self.log(f"  PostgreSQL-Fehler: {r.stderr}")
            return False
        if wait:
            time.sleep(1)
        return True

    def _stop_postgres(self):
        subprocess.run(
            [str(self._pg_ctl), "stop",
             "-D", str(self.data_dir), "-m", "fast"],
            capture_output=True,
        )

    def _psql_exec(self, sql: str):
        subprocess.run(
            [str(self._psql),
             "-h", "127.0.0.1",
             "-p", str(self.app["db_port"]),
             "-U", "postgres",
             "-c", sql],
            capture_output=True,
        )

    def _install_requirements(self) -> bool:
        """Installiert Python-Pakete aus requirements.txt (falls vorhanden)."""
        req_file = Path(self.app["source_path"]) / "requirements.txt"
        if not req_file.exists():
            self.log(f"  [{self.app['name']}] Keine requirements.txt – überspringe pip install.")
            return True
        self.log(f"  [{self.app['name']}] Installiere Pakete (pip install -r requirements.txt) …")
        r = subprocess.run(
            [str(self._py), "-m", "pip", "install", "-r", str(req_file),
             "--quiet", "--disable-pip-version-check"],
            cwd=self.app["source_path"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            # Letzten Teil von stderr anzeigen (nicht die ganze Ausgabe)
            err = r.stderr.strip()[-600:] if r.stderr.strip() else r.stdout.strip()[-600:]
            self.log(f"  pip-Fehler: {err}")
            return False
        self.log(f"  [{self.app['name']}] Pakete installiert.")
        return True

    # ─── Migrationen (öffentlich, für Update-Workflow) ────────────────────

    def _run_migrations(self) -> bool:
        """
        Installiert Pakete + führt Django-Migrationen aus ohne den Server zu starten.
        PostgreSQL muss bereits laufen (wird kurz gestartet und gestoppt).
        """
        # Neue Abhängigkeiten nach git pull installieren
        self._install_requirements()

        pg_was_running = self._is_postgres_running()
        if not pg_was_running and not self._start_postgres(wait=True):
            return False

        env = self._build_env()
        r = subprocess.run(
            [str(self._py), "manage.py", "migrate", "--noinput"],
            cwd=self.app["source_path"],
            env=env,
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            self.log(f"  Migrations-Fehler: {r.stderr}")
        else:
            self.log(f"  [{self.app['name']}] Migrationen OK.")

        subprocess.run(
            [str(self._py), "manage.py", "collectstatic", "--noinput"],
            cwd=self.app["source_path"],
            env=env,
            capture_output=True,
        )

        if not pg_was_running:
            self._stop_postgres()

        return r.returncode == 0

    def _is_port_free(self, port: int) -> bool:
        """True wenn der TCP-Port auf localhost gerade nicht belegt ist."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", port)) != 0

    def setup_done(self) -> bool:
        """True sobald die Ersteinrichtung (initdb) abgeschlossen wurde."""
        return (self.data_dir / "PG_VERSION").exists()

    def create_superuser(
        self, username: str, email: str, password: str
    ) -> tuple[bool, str]:
        """
        Legt einen Django-Superuser an.
        Startet PostgreSQL kurz, falls es nicht läuft.
        Gibt (success, nachricht) zurück.
        """
        pg_was_running = self._is_postgres_running()
        if not pg_was_running and not self._start_postgres(wait=True):
            return False, "PostgreSQL konnte nicht gestartet werden."

        env = self._build_env()
        env["DJANGO_SUPERUSER_PASSWORD"] = password

        r = subprocess.run(
            [
                str(self._py), "manage.py", "createsuperuser",
                "--noinput",
                f"--username={username}",
                f"--email={email}",
            ],
            cwd=self.app["source_path"],
            env=env,
            capture_output=True, text=True,
        )

        if not pg_was_running:
            self._stop_postgres()

        if r.returncode == 0:
            return True, f"Superuser '{username}' wurde erfolgreich erstellt."
        err = (r.stderr or r.stdout).strip()
        return False, err or "Unbekannter Fehler beim Erstellen des Superusers."

    def _is_postgres_running(self) -> bool:
        r = subprocess.run(
            [str(self._pg_ctl), "status", "-D", str(self.data_dir)],
            capture_output=True,
        )
        return r.returncode == 0

    # ─── Django ────────────────────────────────────────────────────────────

    def _start_django(self) -> bool:
        self.log(f"  [{self.app['name']}] Starte Django (Port {self.app['port']}) …")
        env = self._build_env()
        self._write_dotenv(env)
        with self._lock:
            self._dj_proc = subprocess.Popen(
                [str(self._py), "manage.py", "runserver",
                 f"0.0.0.0:{self.app['port']}"],
                cwd=self.app["source_path"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        # Ausgabe im Hintergrund lesen
        threading.Thread(target=self._pipe_output, daemon=True).start()
        time.sleep(2)
        with self._lock:
            return self._dj_proc.poll() is None

    def _pipe_output(self):
        if self._dj_proc and self._dj_proc.stdout:
            for line in self._dj_proc.stdout:
                self.log(f"  [{self.app['name']}] {line.rstrip()}")

    # ─── Umgebungsvariablen ────────────────────────────────────────────────

    def _build_env(self) -> dict:
        env = os.environ.copy()
        env.update({
            "DB_NAME":   self.app["db_name"],
            "DB_USER":   self.app["db_user"],
            "DB_PASS":   self.app["db_password"],
            "DB_HOST":   "127.0.0.1",
            "DB_PORT":   str(self.app["db_port"]),
            "DEBUG":     "True",
            "ALLOWED_HOSTS": self.app.get("allowed_hosts", "localhost,127.0.0.1"),
            "DJANGO_SETTINGS_MODULE": self.app.get("settings_module", "core.settings"),
            "DATABASE_URL": (
                f"postgresql://{self.app['db_user']}:"
                f"{self.app['db_password']}@127.0.0.1:"
                f"{self.app['db_port']}/{self.app['db_name']}"
            ),
        })
        # SECRET_KEY nur setzen wenn explizit konfiguriert
        sk = self.app.get("secret_key", "")
        if sk:
            env["SECRET_KEY"] = sk
        # Weitere benutzerdefinierte Variablen
        try:
            extra = json.loads(self.app.get("extra_env") or "{}")
            env.update({k: str(v) for k, v in extra.items() if k})
        except (json.JSONDecodeError, TypeError):
            pass
        # Portable Python/PostgreSQL lib-Verzeichnis einbinden
        pg_lib = self.postgres_dir / "lib"
        if pg_lib.exists():
            path = env.get("PATH", "")
            env["PATH"] = f"{pg_lib}{os.pathsep}{path}"
        return env

    def _write_dotenv(self, env: dict):
        """Schreibt eine .env-Datei ins App-Quellverzeichnis."""
        src = Path(self.app.get("source_path", ""))
        if not src.is_dir():
            return
        # Feste managed-Keys in sinnvoller Reihenfolge
        managed_keys = [
            "DEBUG", "SECRET_KEY", "ALLOWED_HOSTS", "DJANGO_SETTINGS_MODULE",
            "DB_NAME", "DB_USER", "DB_PASS", "DB_HOST", "DB_PORT", "DATABASE_URL",
        ]
        # Benutzerdefinierte Extra-Keys aus der Konfiguration
        try:
            extra_keys = list(json.loads(self.app.get("extra_env") or "{}").keys())
        except (json.JSONDecodeError, TypeError):
            extra_keys = []
        lines = []
        for k in managed_keys + extra_keys:
            if k in env:
                v = env[k]
                # Werte mit Komma oder Leerzeichen in Anführungszeichen
                lines.append(f'{k}="{v}"\n' if ("," in v or " " in v) else f"{k}={v}\n")
        try:
            (src / ".env").write_text("".join(lines), encoding="utf-8")
            self.log(f"  [{self.app['name']}] .env aktualisiert.")
        except OSError as exc:
            self.log(f"  [{self.app['name']}] .env konnte nicht geschrieben werden: {exc}")
