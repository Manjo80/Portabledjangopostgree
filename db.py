"""
db.py  –  SQLite-basierte Konfigurationsspeicherung
Speichert alle konfigurierten Web-Apps und globale Einstellungen.
"""

import sqlite3
import sys
import threading
from pathlib import Path

# Neben der .exe speichern (portabler Ordner), nicht im PyInstaller-Temp-Ordner
DB_PATH = (
    Path(sys.executable).parent / "apps.db"
    if getattr(sys, "frozen", False)
    else Path(__file__).parent / "apps.db"
)


class Database:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_PATH
        self._lock = threading.Lock()
        self._init()
        self._migrate()

    # ─── Interne Hilfsmethoden ─────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init(self):
        """Erstellt die Tabellen beim ersten Start."""
        with self._lock, self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS apps (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    name          TEXT    NOT NULL UNIQUE,
                    source_path   TEXT    NOT NULL,
                    port          INTEGER NOT NULL DEFAULT 8000,
                    db_name       TEXT    NOT NULL,
                    db_user       TEXT    NOT NULL,
                    db_password   TEXT    NOT NULL,
                    db_port       INTEGER NOT NULL DEFAULT 5433,
                    python_version TEXT   NOT NULL DEFAULT '3.12.8',
                    setup_done    INTEGER NOT NULL DEFAULT 0,
                    -- Git / GitHub
                    source_mode   TEXT    NOT NULL DEFAULT 'local',
                    repo_url      TEXT    NOT NULL DEFAULT '',
                    repo_branch   TEXT    NOT NULL DEFAULT 'main',
                    ssh_key_path  TEXT    NOT NULL DEFAULT '',
                    -- Umgebungsvariablen
                    allowed_hosts   TEXT    NOT NULL DEFAULT 'localhost,127.0.0.1',
                    settings_module TEXT    NOT NULL DEFAULT 'core.settings',
                    secret_key      TEXT    NOT NULL DEFAULT '',
                    extra_env       TEXT    NOT NULL DEFAULT '{}',
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)
            conn.commit()

    def _migrate(self):
        """Fügt neue Spalten zu bestehenden Datenbanken hinzu (forward-only)."""
        new_cols = [
            ("source_mode",    "TEXT NOT NULL DEFAULT 'local'"),
            ("repo_url",       "TEXT NOT NULL DEFAULT ''"),
            ("repo_branch",    "TEXT NOT NULL DEFAULT 'main'"),
            ("ssh_key_path",   "TEXT NOT NULL DEFAULT ''"),
            ("allowed_hosts",  "TEXT NOT NULL DEFAULT 'localhost,127.0.0.1'"),
            ("settings_module","TEXT NOT NULL DEFAULT 'core.settings'"),
            ("secret_key",     "TEXT NOT NULL DEFAULT ''"),
            ("extra_env",      "TEXT NOT NULL DEFAULT '{}'"),
        ]
        with self._lock, self._connect() as conn:
            for col, defn in new_cols:
                try:
                    conn.execute(f"ALTER TABLE apps ADD COLUMN {col} {defn}")
                    conn.commit()
                except sqlite3.OperationalError:
                    pass  # Spalte existiert bereits

    # ─── App-CRUD ──────────────────────────────────────────────────────────

    def get_apps(self) -> list[dict]:
        with self._lock, self._connect() as conn:
            return [dict(r) for r in
                    conn.execute("SELECT * FROM apps ORDER BY name")]

    def get_app(self, app_id: int) -> dict | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM apps WHERE id = ?", (app_id,)
            ).fetchone()
            return dict(row) if row else None

    def add_app(
        self,
        name: str,
        source_path: str,
        port: int,
        db_name: str,
        db_user: str,
        db_password: str,
        db_port: int = 5433,
        python_version: str = "3.12.8",
        source_mode: str = "local",
        repo_url: str = "",
        repo_branch: str = "main",
        ssh_key_path: str = "",
        allowed_hosts: str = "localhost,127.0.0.1",
        settings_module: str = "core.settings",
        secret_key: str = "",
        extra_env: str = "{}",
    ) -> int:
        with self._lock, self._connect() as conn:
            conn.execute(
                """INSERT INTO apps
                   (name, source_path, port, db_name, db_user, db_password,
                    db_port, python_version,
                    source_mode, repo_url, repo_branch, ssh_key_path,
                    allowed_hosts, settings_module, secret_key, extra_env)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, source_path, port, db_name, db_user, db_password,
                 db_port, python_version,
                 source_mode, repo_url, repo_branch, ssh_key_path,
                 allowed_hosts, settings_module, secret_key, extra_env),
            )
            conn.commit()
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def update_app(self, app_id: int, **kwargs):
        if not kwargs:
            return
        with self._lock, self._connect() as conn:
            fields = ", ".join(f"{k} = ?" for k in kwargs)
            values = list(kwargs.values()) + [app_id]
            conn.execute(f"UPDATE apps SET {fields} WHERE id = ?", values)
            conn.commit()

    def delete_app(self, app_id: int):
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM apps WHERE id = ?", (app_id,))
            conn.commit()

    # ─── Einstellungen ─────────────────────────────────────────────────────

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row[0] if row else default

    def set_setting(self, key: str, value: str):
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(value)),
            )
            conn.commit()
