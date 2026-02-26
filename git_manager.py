"""
git_manager.py  –  GitHub / Git Repository Verwaltung
======================================================
Klont und aktualisiert Django-Projekte direkt aus Git-Repositories.
Unterstützt HTTPS und SSH (mit optionalem SSH-Schlüssel).
"""

import os
import shutil
import subprocess
from pathlib import Path


class GitManager:
    """Führt git-Operationen für verwaltete Apps aus."""

    def __init__(self, log_callback=None):
        self.log = log_callback or print
        self._git = shutil.which("git") or "git"

    # ─── Verfügbarkeit ────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Prüft ob Git auf dem System verfügbar ist."""
        try:
            subprocess.run(
                [self._git, "--version"],
                capture_output=True, check=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def get_git_version(self) -> str:
        try:
            r = subprocess.run(
                [self._git, "--version"], capture_output=True, text=True
            )
            return r.stdout.strip()
        except Exception:
            return "nicht gefunden"

    # ─── SSH-Umgebung ─────────────────────────────────────────────────────

    def _env(self, ssh_key_path: str | None = None) -> dict:
        """Baut die Prozess-Umgebung mit optionalem SSH-Schlüssel."""
        env = os.environ.copy()
        if ssh_key_path and Path(ssh_key_path).exists():
            # GIT_SSH_COMMAND überschreibt die Standard-SSH-Konfiguration.
            # StrictHostKeyChecking=accept-new: neuen Host-Keys automatisch
            # akzeptieren, bekannte aber trotzdem prüfen.
            env["GIT_SSH_COMMAND"] = (
                f'ssh -i "{ssh_key_path}" '
                f"-o StrictHostKeyChecking=accept-new "
                f"-o BatchMode=yes"
            )
        return env

    # ─── Klon ─────────────────────────────────────────────────────────────

    def clone(
        self,
        url: str,
        dest: Path,
        branch: str = "main",
        ssh_key_path: str | None = None,
    ) -> bool:
        """
        Klont *url* nach *dest*.
        Falls *dest* bereits ein Git-Repository ist, wird stattdessen pull()
        ausgeführt.
        """
        if dest.exists() and (dest / ".git").exists():
            self.log("  Repository existiert bereits – führe Pull aus.")
            return self.pull(dest, branch, ssh_key_path)

        dest.parent.mkdir(parents=True, exist_ok=True)
        self.log(f"  Klone {url}  →  {dest} …")
        env = self._env(ssh_key_path)

        cmd = [self._git, "clone", "--depth", "1",
               "--branch", branch, url, str(dest)]
        r = subprocess.run(cmd, capture_output=True, text=True, env=env)

        if r.returncode != 0:
            # Branch existiert vielleicht nicht – nochmal ohne --branch
            self.log(
                f"  Branch '{branch}' nicht gefunden, klone Standard-Branch …"
            )
            cmd_plain = [self._git, "clone", "--depth", "1", url, str(dest)]
            r2 = subprocess.run(
                cmd_plain, capture_output=True, text=True, env=env
            )
            if r2.returncode != 0:
                self.log(f"  Git-Fehler: {r2.stderr.strip()}")
                return False

        self.log(f"  Repository geklont.")
        return True

    # ─── Update / Pull ────────────────────────────────────────────────────

    def pull(
        self,
        repo_path: Path,
        branch: str = "main",
        ssh_key_path: str | None = None,
    ) -> bool:
        """
        Aktualisiert ein vorhandenes Repository auf den neuesten Stand.
        Verwendet fetch + reset --hard, um lokale Änderungen zu verwerfen
        und Merge-Konflikte zu vermeiden.
        """
        if not (repo_path / ".git").exists():
            self.log(f"  FEHLER: Kein Git-Repository in {repo_path}")
            return False

        self.log(f"  Aktualisiere {repo_path.name} …")
        env = self._env(ssh_key_path)
        cwd = str(repo_path)

        steps = [
            ([self._git, "fetch", "--prune", "origin"],          "fetch"),
            ([self._git, "checkout", branch],                     f"checkout {branch}"),
            ([self._git, "reset", "--hard", f"origin/{branch}"], "reset"),
        ]

        for cmd, label in steps:
            r = subprocess.run(
                cmd, capture_output=True, text=True, cwd=cwd, env=env
            )
            if r.returncode != 0:
                self.log(f"  Git-Fehler ({label}): {r.stderr.strip()}")
                return False

        commit = self.current_commit(repo_path)
        self.log(f"  Aktualisiert  →  Commit {commit}")
        return True

    # ─── Infos ────────────────────────────────────────────────────────────

    def current_commit(self, repo_path: Path) -> str:
        """Gibt den abgekürzten HEAD-Commit-Hash zurück."""
        r = subprocess.run(
            [self._git, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(repo_path),
        )
        return r.stdout.strip() if r.returncode == 0 else "?"

    def current_branch(self, repo_path: Path) -> str:
        r = subprocess.run(
            [self._git, "branch", "--show-current"],
            capture_output=True, text=True, cwd=str(repo_path),
        )
        return r.stdout.strip() if r.returncode == 0 else "?"

    def remote_url(self, repo_path: Path) -> str:
        r = subprocess.run(
            [self._git, "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=str(repo_path),
        )
        return r.stdout.strip() if r.returncode == 0 else ""

    def is_cloned(self, repo_path: Path) -> bool:
        return repo_path.exists() and (repo_path / ".git").exists()
