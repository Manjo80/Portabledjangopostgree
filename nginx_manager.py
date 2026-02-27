"""
nginx_manager.py  –  Portabler nginx-Wrapper für Windows
=========================================================
Lädt nginx automatisch herunter, generiert nginx.conf pro App
und verwaltet den nginx-Prozess.

nginx.exe muss entweder vorhanden sein unter:
  <BASE_DIR>/nginx/nginx-<VERSION>/nginx.exe
oder auf dem System-PATH.

Bei aktiviertem Auto-Download wird es von nginx.org geladen.
"""

import shutil
import subprocess
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable

# ─── nginx-Version & Download ─────────────────────────────────────────────────
NGINX_VERSION      = "1.26.3"
NGINX_DOWNLOAD_URL = f"https://nginx.org/download/nginx-{NGINX_VERSION}.zip"
NGINX_ZIP_NAME     = f"nginx-{NGINX_VERSION}.zip"
NGINX_DIR_NAME     = f"nginx-{NGINX_VERSION}"

# ─── nginx.conf-Template ──────────────────────────────────────────────────────
_CONF_TEMPLATE = """\
# Automatisch generiert von Portable Django Manager
# App: {app_name}  |  nginx-Port: {nginx_port}  |  Django-Port: {django_port}

worker_processes 1;

events {{
    worker_connections 64;
}}

http {{
    include       mime.types;
    default_type  application/octet-stream;

    sendfile        on;
    keepalive_timeout 65;

    access_log  {log_dir_fwd}/access_{app_slug}.log;
    error_log   {log_dir_fwd}/error_{app_slug}.log  warn;

    server {{
        listen       {nginx_port};
        server_name  localhost 127.0.0.1;

        # ── Statische Dateien (direkt von STATIC_ROOT, kein Django) ──────
        location /static/ {{
            alias {static_root_fwd}/;
            expires 7d;
            add_header Cache-Control "public, immutable";
            gzip_static on;
        }}

        # ── Media-Dateien ──────────────────────────────────────────────────
        location /media/ {{
            alias {media_root_fwd}/;
            expires 1d;
        }}

        # ── Alle anderen Anfragen → Django runserver ───────────────────────
        location / {{
            proxy_pass         http://127.0.0.1:{django_port};
            proxy_set_header   Host              $host;
            proxy_set_header   X-Real-IP         $remote_addr;
            proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header   X-Forwarded-Proto $scheme;
            proxy_connect_timeout 300s;
            proxy_send_timeout    300s;
            proxy_read_timeout    300s;
            client_max_body_size  100m;
        }}

        # ── Fehlerseiten ───────────────────────────────────────────────────
        error_page 502 503 504 /50x.html;
        location = /50x.html {{
            root html;
        }}
    }}
}}
"""


def _fwd(path) -> str:
    """Pfad mit Forward-Slashes (nginx versteht keine Backslashes)."""
    return str(path).replace("\\", "/")


class NginxManager:
    """
    Verwaltet einen portablen nginx-Prozess als Reverse-Proxy vor einer
    Django-App.

    nginx-Verzeichnis-Layout unter <BASE_DIR>/nginx/:
      nginx-1.26.3/           ← entpacktes nginx-Archiv (nginx.exe hier drin)
        nginx.exe
        conf/
          mime.types          ← wird von nginx benötigt
        ...
      conf_apps/<app_id>/     ← generierte nginx.conf pro App
        nginx.conf
        mime.types            ← Kopie für standalone-Konfig
      logs/                   ← Access- und Error-Logs pro App
    """

    def __init__(
        self,
        base_dir: Path,
        app: dict,
        log_callback: Callable[[str], None] | None = None,
    ):
        self.base_dir = base_dir
        self.app      = app
        self.log      = log_callback or print
        self._proc: subprocess.Popen | None = None
        self._lock    = threading.Lock()

    # ── Pfade ─────────────────────────────────────────────────────────────

    @property
    def nginx_base(self) -> Path:
        """<BASE_DIR>/nginx/"""
        return self.base_dir / "nginx"

    @property
    def nginx_exe(self) -> Path:
        """<BASE_DIR>/nginx/nginx-<VERSION>/nginx.exe"""
        return self.nginx_base / NGINX_DIR_NAME / "nginx.exe"

    @property
    def _conf_dir(self) -> Path:
        d = self.nginx_base / "conf_apps" / str(self.app["id"])
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def _log_dir(self) -> Path:
        d = self.nginx_base / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── nginx-Binary ──────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """True wenn nginx.exe unter BASE_DIR/nginx/ oder auf PATH gefunden."""
        return self._find_exe() is not None

    def _find_exe(self) -> Path | None:
        if self.nginx_exe.exists():
            return self.nginx_exe
        w = shutil.which("nginx")
        return Path(w) if w else None

    def download_nginx(self) -> bool:
        """
        Lädt nginx portable für Windows von nginx.org herunter und entpackt es.
        Gibt True zurück wenn erfolgreich.
        """
        import urllib.request

        self.nginx_base.mkdir(parents=True, exist_ok=True)
        zip_path = self.nginx_base / NGINX_ZIP_NAME

        self.log(f"  [nginx] Lade nginx {NGINX_VERSION} von nginx.org herunter …")
        self.log(f"  [nginx] URL: {NGINX_DOWNLOAD_URL}")
        try:
            urllib.request.urlretrieve(NGINX_DOWNLOAD_URL, str(zip_path))
        except Exception as exc:
            self.log(f"  [nginx] ❌ Download fehlgeschlagen: {exc}")
            return False

        self.log(f"  [nginx] Entpacke …")
        try:
            with zipfile.ZipFile(str(zip_path), "r") as zf:
                zf.extractall(str(self.nginx_base))
        except Exception as exc:
            self.log(f"  [nginx] ❌ Entpacken fehlgeschlagen: {exc}")
            return False

        zip_path.unlink(missing_ok=True)
        if self.nginx_exe.exists():
            self.log(f"  [nginx] ✅ nginx {NGINX_VERSION} bereit ({self.nginx_exe})")
            return True
        else:
            self.log(f"  [nginx] ❌ nginx.exe nach Entpacken nicht gefunden: {self.nginx_exe}")
            return False

    def ensure_available(self) -> bool:
        """nginx bereitstellen: herunterladen wenn nötig."""
        if self.is_available():
            return True
        self.log(
            f"  [nginx] nginx.exe nicht gefunden. Automatischer Download …\n"
            f"  [nginx] (Ablegen unter: {self.nginx_base}\\{NGINX_DIR_NAME}\\nginx.exe)"
        )
        return self.download_nginx()

    # ── nginx.conf generieren ─────────────────────────────────────────────

    def _write_conf(self, exe: Path) -> Path:
        """Generiert nginx.conf für diese App und gibt den Pfad zurück."""
        source   = Path(self.app["source_path"])
        app_slug = self.app["name"].replace(" ", "_").replace("/", "_")

        # mime.types aus dem nginx-Paket kopieren (nginx braucht es)
        mime_src = exe.parent / "conf" / "mime.types"
        mime_dst = self._conf_dir / "mime.types"
        if mime_src.exists():
            shutil.copy2(str(mime_src), str(mime_dst))

        conf = _CONF_TEMPLATE.format(
            app_name     = self.app["name"],
            app_slug     = app_slug,
            nginx_port   = self.app.get("nginx_port", 80),
            django_port  = self.app["port"],
            static_root_fwd = _fwd(source / "staticfiles"),
            media_root_fwd  = _fwd(source / "media"),
            log_dir_fwd     = _fwd(self._log_dir),
        )

        conf_path = self._conf_dir / "nginx.conf"
        conf_path.write_text(conf, encoding="utf-8")
        return conf_path

    # ── Start / Stop ──────────────────────────────────────────────────────

    def start(self) -> bool:
        """
        nginx starten.
        Gibt True zurück wenn nginx erfolgreich läuft.
        """
        if not self.ensure_available():
            self.log(
                f"  [nginx] ❌ nginx nicht verfügbar.\n"
                f"  [nginx]    Manuell: nginx.exe in {self.nginx_base}\\{NGINX_DIR_NAME}\\ ablegen."
            )
            return False

        exe = self._find_exe()
        if exe is None:
            return False

        # Sicherstellen dass logs/-Verzeichnis im nginx-prefix existiert
        # (nginx legt dort intern nginx.pid ab)
        nginx_prefix     = exe.parent
        prefix_logs_dir  = nginx_prefix / "logs"
        prefix_logs_dir.mkdir(parents=True, exist_ok=True)
        prefix_temp_dir  = nginx_prefix / "temp"
        prefix_temp_dir.mkdir(parents=True, exist_ok=True)

        conf_path = self._write_conf(exe)
        nginx_port = self.app.get("nginx_port", 80)

        cmd = [
            str(exe),
            "-c", _fwd(conf_path),
            "-p", _fwd(nginx_prefix),
        ]

        self.log(f"  [nginx] Starte auf Port {nginx_port} …")
        try:
            with self._lock:
                self._proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            time.sleep(1.0)
            with self._lock:
                rc = self._proc.poll()
                if rc is not None:
                    err = ""
                    if self._proc.stderr:
                        err = self._proc.stderr.read(600)
                    self.log(f"  [nginx] ❌ Sofort beendet (rc={rc}): {err.strip()}")
                    self._proc = None
                    return False

            self.log(
                f"  [nginx] ✅ Bereit → http://localhost:{nginx_port}  "
                f"(Proxy → Django :{self.app['port']})"
            )
            return True

        except Exception as exc:
            self.log(f"  [nginx] ❌ Startfehler: {exc}")
            with self._lock:
                self._proc = None
            return False

    def stop(self):
        """nginx ordentlich beenden."""
        with self._lock:
            proc = self._proc
            self._proc = None

        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.log(f"  [nginx] Gestoppt.")

    def is_running(self) -> bool:
        """True wenn nginx-Prozess läuft."""
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def reload(self):
        """nginx-Konfiguration neu laden (ohne Neustart)."""
        with self._lock:
            proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.send_signal(subprocess.signal.SIGHUP)
            except Exception:
                pass  # Windows unterstützt SIGHUP nicht zuverlässig

    # ── Info ──────────────────────────────────────────────────────────────

    def status_text(self) -> str:
        """Kurzer Status-String für die UI."""
        if not self.is_available():
            return "nginx: nicht installiert"
        if self.is_running():
            return f"nginx: ●  Port {self.app.get('nginx_port', 80)}"
        return "nginx: ○  gestoppt"
