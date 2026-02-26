"""
Portable Django Manager  –  Grafisches Verwaltungs-Tool
========================================================
Verwaltet mehrere Django-Webanwendungen mit eingebettetem Python
und portatiblem PostgreSQL auf einem Windows-Rechner.

Quelle: lokaler Ordner  ODER  GitHub / Git-Repository (HTTPS / SSH).

Benötigt:  pip install customtkinter
Paketieren: build_exe.bat  (erzeugt portable .exe via PyInstaller)
"""

import json
import secrets
import string
import subprocess
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

from db import Database
from git_manager import GitManager
from runner import AppRunner, BASE_DIR

# ─── Erscheinungsbild ─────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

REPOS_DIR = BASE_DIR / "repos"

# ─── Pink-Elefant-Logo ────────────────────────────────────────────────────────
PINK = "#e91e8c"   # Marken-Pink
PINK_DARK = "#c0156f"


def _draw_elephant(canvas: tk.Canvas, ox: int, oy: int, scale: float = 1.0,
                   color: str = PINK) -> None:
    """
    Zeichnet eine stilisierte Elefanten-Silhouette auf *canvas*.
    ox/oy = Ursprung (oben-links des Bounding-Box).
    scale = 1.0 entspricht einer Bounding-Box von 88 × 72 px.
    """
    def s(v):
        return v * scale

    # Ohr (hinter Kopf, etwas dunkler)
    canvas.create_oval(
        ox + s(2),  oy + s(6),
        ox + s(34), oy + s(44),
        fill=PINK_DARK, outline="")

    # Körper
    canvas.create_oval(
        ox + s(28), oy + s(16),
        ox + s(88), oy + s(58),
        fill=color, outline="")

    # Kopf
    canvas.create_oval(
        ox + s(4),  oy + s(8),
        ox + s(46), oy + s(46),
        fill=color, outline="")

    # Rüssel (hängt nach unten)
    canvas.create_polygon(
        ox + s(7),  oy + s(40),
        ox + s(20), oy + s(40),
        ox + s(24), oy + s(58),
        ox + s(20), oy + s(66),
        ox + s(12), oy + s(64),
        ox + s(8),  oy + s(54),
        fill=color, outline="")

    # Rüssel-Spitze abrunden
    canvas.create_oval(
        ox + s(10), oy + s(58),
        ox + s(24), oy + s(68),
        fill=color, outline="")

    # Beine (4 abgerundete Rechtecke)
    for lx in [s(32), s(44), s(56), s(68)]:
        canvas.create_rectangle(
            ox + lx,        oy + s(52),
            ox + lx + s(10), oy + s(72),
            fill=color, outline="")
        canvas.create_oval(
            ox + lx,        oy + s(64),
            ox + lx + s(10), oy + s(72),
            fill=color, outline="")

    # Schwanz
    canvas.create_polygon(
        ox + s(84), oy + s(24),
        ox + s(92), oy + s(16),
        ox + s(94), oy + s(26),
        ox + s(88), oy + s(32),
        fill=color, outline="")

    # Auge (weiß + Pupille)
    canvas.create_oval(
        ox + s(18), oy + s(16),
        ox + s(28), oy + s(26),
        fill="white", outline="")
    canvas.create_oval(
        ox + s(21), oy + s(19),
        ox + s(26), oy + s(24),
        fill="#1a1a1a", outline="")


# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

def _detect_settings_module(project_dir: Path) -> str | None:
    """
    Sucht in project_dir nach einer settings.py und gibt den Python-Modulpfad
    zurück (z.B. 'myapp.settings'). Gibt None zurück wenn nichts gefunden.
    """
    if not project_dir.is_dir() or not (project_dir / "manage.py").exists():
        return None
    _SKIP = {"venv", "env", ".venv", ".env", "__pycache__", ".git",
             "node_modules", "site-packages", "dist-packages"}
    found: list[Path] = []
    try:
        for p in project_dir.rglob("settings.py"):
            parts = set(p.relative_to(project_dir).parts[:-1])
            if parts & _SKIP:
                continue
            found.append(p)
    except (OSError, ValueError):
        return None
    if not found:
        return None
    target = next(
        (f for f in found
         if not any(s in f.parent.name for s in ("dev", "prod", "local", "test"))),
        found[0],
    )
    return ".".join(target.relative_to(project_dir).with_suffix("").parts)


def _random_password(length: int = 20) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def _slug(text: str) -> str:
    return text.lower().strip().replace(" ", "_").replace("-", "_")


# ─── SSH-Key-Manager ─────────────────────────────────────────────────────────

class SshKeyDialog(ctk.CTkToplevel):
    """
    Generiert ein Ed25519-Schlüsselpaar, zeigt den Public Key zum
    Eintragen bei GitHub und setzt den privaten Schlüsselpfad zurück.

    Aufruf:
        dlg = SshKeyDialog(parent, app_slug="meinprojekt")
        parent.wait_window(dlg)
        priv_path = dlg.result_priv_path   # "" wenn abgebrochen
    """

    GITHUB_SSH_URL = "https://github.com/settings/ssh/new"

    def __init__(self, parent, app_slug: str = ""):
        super().__init__(parent)
        self.title("SSH-Schlüssel verwalten")
        self.geometry("530x530")
        self.resizable(False, False)
        self.grab_set()

        self.result_priv_path: str = ""
        self._pub_key_text: str = ""

        pad = {"padx": 20, "pady": 4}

        # ── Kopfzeile ─────────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="SSH-Schlüsselpaar erstellen",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).pack(**pad, pady=(20, 4))

        ctk.CTkLabel(
            self,
            text=(
                "Erstellt einen neuen Ed25519-Schlüssel.\n"
                "Den Public Key trägst du bei GitHub ein,\n"
                "der Private Key bleibt auf deinem PC."
            ),
            text_color="gray55",
            font=ctk.CTkFont(size=11),
            justify="left",
        ).pack(padx=20, pady=(0, 8), anchor="w")

        ctk.CTkFrame(self, height=1, fg_color="gray30").pack(fill="x", padx=20, pady=4)

        # ── Schlüsselname ────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Schlüsselname:", anchor="w").pack(
            fill="x", padx=20, pady=(10, 0))
        self.v_keyname = ctk.StringVar(
            value=f"id_ed25519_{app_slug}" if app_slug else "id_ed25519_portable"
        )
        ctk.CTkEntry(self, textvariable=self.v_keyname).pack(
            fill="x", padx=20, pady=(2, 0))

        # ── Speicherort ───────────────────────────────────────────────────
        ctk.CTkLabel(self, text="Speicherort:", anchor="w").pack(
            fill="x", padx=20, pady=(10, 0))
        loc_row = ctk.CTkFrame(self, fg_color="transparent")
        loc_row.pack(fill="x", padx=20, pady=(2, 0))
        loc_row.grid_columnconfigure(0, weight=1)
        self.v_key_dir = ctk.StringVar(value=str(Path.home() / ".ssh"))
        ctk.CTkEntry(loc_row, textvariable=self.v_key_dir).grid(
            row=0, column=0, sticky="ew")
        ctk.CTkButton(
            loc_row, text="…", width=36,
            command=self._browse_dir,
        ).grid(row=0, column=1, padx=(6, 0))

        # ── Erstellen-Button ──────────────────────────────────────────────
        self._gen_btn = ctk.CTkButton(
            self, text="🔑  Schlüsselpaar erstellen",
            command=self._generate,
        )
        self._gen_btn.pack(padx=20, pady=14, fill="x")

        # ── Statuszeile ───────────────────────────────────────────────────
        self._status_lbl = ctk.CTkLabel(
            self, text="", text_color="gray55",
            font=ctk.CTkFont(size=11),
        )
        self._status_lbl.pack(padx=20)

        ctk.CTkFrame(self, height=1, fg_color="gray30").pack(
            fill="x", padx=20, pady=(8, 4))

        # ── Public-Key-Anzeige ────────────────────────────────────────────
        pub_hdr = ctk.CTkFrame(self, fg_color="transparent")
        pub_hdr.pack(fill="x", padx=20, pady=(4, 0))
        ctk.CTkLabel(
            pub_hdr,
            text="Public Key  →  bei GitHub eintragen:",
            font=ctk.CTkFont(weight="bold"),
            anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            pub_hdr,
            text="(für GitHub — öffentlich, kein Geheimnis)",
            text_color=PINK,
            font=ctk.CTkFont(size=10),
        ).pack(side="left", padx=(8, 0))

        self._pub_box = ctk.CTkTextbox(self, height=72, wrap="word",
                                        font=ctk.CTkFont(family="Courier", size=10))
        self._pub_box.pack(fill="x", padx=20, pady=(4, 0))
        self._pub_box.configure(state="disabled")

        # ── Aktions-Buttons für Public Key ────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=8)
        ctk.CTkButton(
            btn_row, text="📋  Kopieren",
            width=130,
            command=self._copy_pub,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_row, text="⬇  .pub speichern",
            width=140,
            fg_color="gray40", hover_color="gray30",
            command=self._save_pub,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_row, text="🌐  GitHub öffnen",
            width=140,
            fg_color="gray40", hover_color="gray30",
            command=lambda: webbrowser.open(self.GITHUB_SSH_URL),
        ).pack(side="left")

        # ── Hinweis Private Key ───────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text=(
                "⚠  Private Key (.pem / id_*) — niemals hochladen oder teilen!\n"
                "   Nach dem Erstellen wird der Pfad automatisch ins SSH-Feld übernommen."
            ),
            text_color="gray50",
            font=ctk.CTkFont(size=10),
            justify="left",
        ).pack(padx=20, anchor="w")

        # ── Schließen ─────────────────────────────────────────────────────
        ctk.CTkButton(
            self, text="Übernehmen & Schließen",
            command=self._accept,
        ).pack(pady=14)

    # ── interne Methoden ──────────────────────────────────────────────────────

    def _browse_dir(self):
        d = filedialog.askdirectory(
            title="Speicherort wählen",
            initialdir=self.v_key_dir.get(),
            parent=self,
        )
        if d:
            self.v_key_dir.set(d)

    def _generate(self):
        key_dir  = Path(self.v_key_dir.get().strip())
        key_name = self.v_keyname.get().strip()
        if not key_name:
            self._set_status("⚠ Bitte einen Schlüsselnamen eingeben.", "orange")
            return

        key_dir.mkdir(parents=True, exist_ok=True)
        priv_path = key_dir / key_name
        pub_path  = key_dir / f"{key_name}.pub"

        if priv_path.exists():
            self._set_status(
                f"⚠  '{key_name}' existiert bereits. Namen ändern oder Datei löschen.",
                "orange"
            )
            return

        try:
            result = subprocess.run(
                [
                    "ssh-keygen",
                    "-t", "ed25519",
                    "-f", str(priv_path),
                    "-N", "",          # kein Passwort
                    "-C", f"portable-django-{key_name}",
                ],
                capture_output=True, text=True, timeout=15,
            )
        except FileNotFoundError:
            self._set_status(
                "⚠  ssh-keygen nicht gefunden. OpenSSH unter Windows installieren.", "red"
            )
            return
        except subprocess.TimeoutExpired:
            self._set_status("⚠  Zeitüberschreitung bei ssh-keygen.", "red")
            return

        if result.returncode != 0:
            self._set_status(f"⚠  Fehler: {result.stderr.strip()}", "red")
            return

        # Public Key einlesen und anzeigen
        self._pub_key_text = pub_path.read_text(encoding="utf-8").strip()
        self._pub_box.configure(state="normal")
        self._pub_box.delete("1.0", "end")
        self._pub_box.insert("1.0", self._pub_key_text)
        self._pub_box.configure(state="disabled")

        self.result_priv_path = str(priv_path)
        self._set_status(
            f"✅  Schlüssel erstellt: {priv_path.name}  (+ {key_name}.pub)",
            "green"
        )

    def _copy_pub(self):
        if not self._pub_key_text:
            self._set_status("⚠  Zuerst einen Schlüssel erstellen.", "orange")
            return
        self.clipboard_clear()
        self.clipboard_append(self._pub_key_text)
        self._set_status("✅  Public Key in Zwischenablage kopiert.", "green")

    def _save_pub(self):
        if not self._pub_key_text:
            self._set_status("⚠  Zuerst einen Schlüssel erstellen.", "orange")
            return
        dest = filedialog.asksaveasfilename(
            title="Public Key speichern (.pub)",
            defaultextension=".pub",
            filetypes=[("Public Key", "*.pub"), ("Alle Dateien", "*")],
            initialfile=f"{self.v_keyname.get()}.pub",
            initialdir=str(Path.home() / "Desktop"),
            parent=self,
        )
        if dest:
            Path(dest).write_text(self._pub_key_text, encoding="utf-8")
            self._set_status(f"✅  Public Key gespeichert: {Path(dest).name}", "green")

    def _accept(self):
        self.destroy()

    def _set_status(self, msg: str, color: str = "gray55"):
        colors = {"green": "#4caf50", "orange": "#ff9800", "red": "#f44336", "gray55": "gray55"}
        self._status_lbl.configure(text=msg, text_color=colors.get(color, color))


# ─── About-Dialog ────────────────────────────────────────────────────────────

class AboutDialog(ctk.CTkToplevel):
    """Über-Dialog mit Pink-Elefant-Logo und App-Informationen."""

    _BG = "#111111"

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Über Portable Django Manager")
        self.geometry("420x440")
        self.resizable(False, False)
        self.grab_set()
        self.configure(fg_color=("gray95", "#1a1a1a"))

        # ── Logo-Panel ────────────────────────────────────────────────────
        logo_panel = ctk.CTkFrame(self, fg_color=self._BG, corner_radius=16)
        logo_panel.pack(fill="x", padx=24, pady=(24, 0))

        # Canvas für Elefant
        cv = tk.Canvas(logo_panel, width=96, height=78,
                       bg=self._BG, highlightthickness=0)
        cv.pack(pady=(20, 4))
        _draw_elephant(cv, ox=1, oy=3, scale=1.0)

        ctk.CTkLabel(
            logo_panel,
            text="PINK ELEFANT",
            font=ctk.CTkFont(family="Arial", size=22, weight="bold"),
            text_color=PINK,
        ).pack()

        ctk.CTkLabel(
            logo_panel,
            text="Software & Webentwicklung",
            font=ctk.CTkFont(size=11),
            text_color="gray55",
        ).pack(pady=(2, 18))

        # ── App-Info ──────────────────────────────────────────────────────
        ctk.CTkLabel(
            self,
            text="Portable Django Manager",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(pady=(18, 2))

        ctk.CTkLabel(
            self,
            text="Version 1.1",
            text_color="gray55",
            font=ctk.CTkFont(size=12),
        ).pack()

        ctk.CTkLabel(
            self,
            text=(
                "Verwaltet mehrere Django-Webanwendungen mit\n"
                "portablem Python und PostgreSQL auf Windows.\n"
                "Kein Admin-Zugriff erforderlich."
            ),
            font=ctk.CTkFont(size=11),
            text_color="gray55",
            justify="center",
        ).pack(pady=(10, 6))

        ctk.CTkFrame(self, height=1, fg_color="gray30").pack(
            fill="x", padx=32, pady=6
        )

        ctk.CTkLabel(
            self,
            text="© 2025 Pink Elefant",
            text_color="gray50",
            font=ctk.CTkFont(size=11),
        ).pack(pady=(4, 0))

        ctk.CTkButton(
            self, text="Schließen", width=130,
            command=self.destroy,
        ).pack(pady=18)


# ─── Superuser-Dialog ────────────────────────────────────────────────────────

class SuperuserDialog(ctk.CTkToplevel):
    """Kleiner Dialog zum Erstellen eines Django-Superusers."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Django-Superuser erstellen")
        self.geometry("400x295")
        self.resizable(False, False)
        self.grab_set()
        self.result: dict | None = None

        pad = {"padx": 22, "pady": 7}
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Benutzername:", anchor="w").grid(
            row=0, column=0, sticky="w", **pad)
        self.v_user = ctk.StringVar(value="admin")
        ctk.CTkEntry(self, textvariable=self.v_user).grid(
            row=0, column=1, sticky="ew", **pad)

        ctk.CTkLabel(self, text="E-Mail:", anchor="w").grid(
            row=1, column=0, sticky="w", **pad)
        self.v_email = ctk.StringVar(value="admin@example.com")
        ctk.CTkEntry(self, textvariable=self.v_email).grid(
            row=1, column=1, sticky="ew", **pad)

        ctk.CTkLabel(self, text="Passwort:", anchor="w").grid(
            row=2, column=0, sticky="w", **pad)
        self.v_pass = ctk.StringVar()
        ctk.CTkEntry(self, textvariable=self.v_pass, show="●").grid(
            row=2, column=1, sticky="ew", **pad)

        ctk.CTkLabel(self, text="Passwort (wdh.):", anchor="w").grid(
            row=3, column=0, sticky="w", **pad)
        self.v_pass2 = ctk.StringVar()
        ctk.CTkEntry(self, textvariable=self.v_pass2, show="●").grid(
            row=3, column=1, sticky="ew", **pad)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=4, column=0, columnspan=2, pady=18)
        ctk.CTkButton(btns, text="Erstellen", width=140,
                      command=self._save).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="Abbrechen", width=140,
                      command=self.destroy).pack(side="left", padx=8)

    def _save(self):
        u = self.v_user.get().strip()
        e = self.v_email.get().strip()
        p  = self.v_pass.get()
        p2 = self.v_pass2.get()
        if not u:
            messagebox.showwarning("Eingabe fehlt", "Benutzername darf nicht leer sein.", parent=self)
            return
        if not p:
            messagebox.showwarning("Eingabe fehlt", "Passwort darf nicht leer sein.", parent=self)
            return
        if p != p2:
            messagebox.showwarning("Passwort", "Die Passwörter stimmen nicht überein.", parent=self)
            return
        self.result = {"username": u, "email": e, "password": p}
        self.destroy()


# ─── App-Dialog (Hinzufügen / Bearbeiten) ────────────────────────────────────

class AppDialog(ctk.CTkToplevel):
    """
    Modaler Dialog zum Anlegen oder Bearbeiten einer App-Konfiguration.
    Unterstützt zwei Quell-Modi:
      • Lokal  – Ordner auf dem PC / Netzlaufwerk
      • GitHub – Repository per HTTPS oder SSH (mit optionalem SSH-Key)
    """

    def __init__(self, parent, app: dict | None = None):
        super().__init__(parent)
        self.app = app
        self.result: dict | None = None

        self.title("App bearbeiten" if app else "Neue App hinzufügen")
        self.geometry("580x940")
        self.resizable(False, True)
        self.transient(parent)
        self.grab_set()
        self.lift()

        self._build()
        if app:
            self._fill(app)

    # ── Layout ────────────────────────────────────────────────────────────

    def _build(self):
        pad = {"padx": 20, "pady": 5}
        self.grid_columnconfigure(1, weight=1)

        r = 0

        # Titel
        ctk.CTkLabel(
            self,
            text="App-Konfiguration",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=r, column=0, columnspan=3, sticky="w", padx=20, pady=(18, 8))
        r += 1

        # Name
        self.v_name = ctk.StringVar()
        self._lbl_row(r, "Name:", ctk.CTkEntry(self, textvariable=self.v_name)); r += 1

        # ── Quell-Modus Toggle ────────────────────────────────────────────
        ctk.CTkLabel(self, text="Quelle:", anchor="w").grid(
            row=r, column=0, sticky="w", **pad
        )
        self.v_mode = ctk.StringVar(value="local")
        seg = ctk.CTkSegmentedButton(
            self,
            values=["📁  Lokaler Ordner", "🐙  GitHub / Git"],
            variable=self.v_mode,
            command=self._on_mode_change,
        )
        seg.grid(row=r, column=1, columnspan=2, sticky="ew", **pad)
        r += 1

        # ── Lokaler Ordner ────────────────────────────────────────────────
        self._local_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._local_frame.grid_columnconfigure(0, weight=1)
        self.v_source = ctk.StringVar()
        ctk.CTkEntry(
            self._local_frame,
            textvariable=self.v_source,
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            self._local_frame, text="…", width=36, command=self._browse_local
        ).grid(row=0, column=1, padx=(6, 0))

        ctk.CTkLabel(self, text="Verzeichnis:", anchor="w").grid(
            row=r, column=0, sticky="w", **pad
        )
        self._local_frame.grid(row=r, column=1, columnspan=2, sticky="ew", **pad)
        self._local_row = r
        r += 1

        # ── GitHub / Git ──────────────────────────────────────────────────
        self._git_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._git_frame.grid_columnconfigure(1, weight=1)

        def gf_lbl(gr, text):
            ctk.CTkLabel(
                self._git_frame, text=text, anchor="w"
            ).grid(row=gr, column=0, sticky="w", padx=(0, 10), pady=4)

        # Repo-URL
        self.v_repo_url = ctk.StringVar()
        gf_lbl(0, "Repository-URL:")
        ctk.CTkEntry(
            self._git_frame, textvariable=self.v_repo_url,
            placeholder_text="https://github.com/user/repo  oder  git@github.com:user/repo.git",
        ).grid(row=0, column=1, columnspan=2, sticky="ew", pady=4)

        # Branch
        self.v_branch = ctk.StringVar(value="main")
        gf_lbl(1, "Branch:")
        ctk.CTkEntry(
            self._git_frame, textvariable=self.v_branch, width=160
        ).grid(row=1, column=1, sticky="w", pady=4)

        # SSH-Schlüssel (optional)
        self.v_ssh_key = ctk.StringVar()
        gf_lbl(2, "SSH-Schlüssel\n(optional):")
        ssh_row = ctk.CTkFrame(self._git_frame, fg_color="transparent")
        ssh_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(
            ssh_row, textvariable=self.v_ssh_key,
            placeholder_text="Leer lassen für HTTPS / Standard-SSH",
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            ssh_row, text="…", width=36, command=self._browse_ssh_key,
        ).grid(row=0, column=1, padx=(6, 0))
        ctk.CTkButton(
            ssh_row, text="🔑", width=36,
            fg_color=PINK, hover_color=PINK_DARK,
            command=self._open_ssh_manager,
        ).grid(row=0, column=2, padx=(4, 0))
        ssh_row.grid(row=2, column=1, columnspan=2, sticky="ew", pady=4)

        ctk.CTkLabel(
            self._git_frame,
            text=(
                "HTTPS: kein Schlüssel nötig  ·  SSH: privaten Schlüssel wählen  ·  "
                "🔑 = neuen Schlüssel erstellen & für GitHub exportieren"
            ),
            text_color="gray55", font=ctk.CTkFont(size=11),
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(0, 4))

        ctk.CTkLabel(self, text="Repository:", anchor="w").grid(
            row=r, column=0, sticky="nw", **pad
        )
        self._git_frame.grid(row=r, column=1, columnspan=2, sticky="ew", **pad)
        self._git_row = r
        r += 1

        # Port
        self.v_port = ctk.StringVar(value="8000")
        self._lbl_row(r, "App-Port:", ctk.CTkEntry(self, textvariable=self.v_port, width=100)); r += 1

        # Trennlinie
        ctk.CTkFrame(self, height=1, fg_color="gray30").grid(
            row=r, column=0, columnspan=3, sticky="ew", padx=20, pady=8
        ); r += 1
        ctk.CTkLabel(
            self, text="Datenbank", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=r, column=0, columnspan=3, sticky="w", padx=20); r += 1

        # DB-Felder
        self.v_db_name = ctk.StringVar()
        self._lbl_row(r, "Datenbankname:", ctk.CTkEntry(self, textvariable=self.v_db_name)); r += 1

        self.v_db_user = ctk.StringVar()
        self._lbl_row(r, "DB-Benutzer:", ctk.CTkEntry(self, textvariable=self.v_db_user)); r += 1

        self.v_db_pass = ctk.StringVar()
        pw_frame = ctk.CTkFrame(self, fg_color="transparent")
        pw_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(pw_frame, textvariable=self.v_db_pass, show="●").grid(
            row=0, column=0, sticky="ew"
        )
        ctk.CTkButton(
            pw_frame, text="⟳", width=36,
            command=lambda: self.v_db_pass.set(_random_password()),
        ).grid(row=0, column=1, padx=(6, 0))
        ctk.CTkLabel(self, text="DB-Passwort:", anchor="w").grid(
            row=r, column=0, sticky="w", **pad
        )
        pw_frame.grid(row=r, column=1, columnspan=2, sticky="ew", **pad); r += 1

        self.v_db_port = ctk.StringVar(value="5433")
        self._lbl_row(r, "DB-Port:", ctk.CTkEntry(self, textvariable=self.v_db_port, width=100)); r += 1

        # ── Umgebungsvariablen ────────────────────────────────────────────
        ctk.CTkFrame(self, height=1, fg_color="gray30").grid(
            row=r, column=0, columnspan=3, sticky="ew", padx=20, pady=8
        ); r += 1
        ctk.CTkLabel(
            self, text="Umgebungsvariablen", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=r, column=0, columnspan=3, sticky="w", padx=20); r += 1

        # DJANGO_SETTINGS_MODULE
        self.v_settings_module = ctk.StringVar(value="core.settings")
        self._lbl_row(r, "Settings-Modul:", ctk.CTkEntry(
            self, textvariable=self.v_settings_module,
            placeholder_text="core.settings  (z.B. myapp.settings.local)",
        )); r += 1

        # ALLOWED_HOSTS
        self.v_allowed_hosts = ctk.StringVar(value="localhost,127.0.0.1")
        self._lbl_row(r, "Allowed Hosts:", ctk.CTkEntry(
            self, textvariable=self.v_allowed_hosts,
            placeholder_text="localhost,127.0.0.1,meinserver.local",
        )); r += 1

        # SECRET_KEY
        self.v_secret_key = ctk.StringVar()
        sk_frame = ctk.CTkFrame(self, fg_color="transparent")
        sk_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(
            sk_frame, textvariable=self.v_secret_key,
            placeholder_text="Leer = Wert aus settings.py wird verwendet",
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            sk_frame, text="⟳", width=36,
            command=lambda: self.v_secret_key.set(_random_password(50)),
        ).grid(row=0, column=1, padx=(6, 0))
        ctk.CTkLabel(self, text="SECRET_KEY:", anchor="w").grid(
            row=r, column=0, sticky="w", **pad
        )
        sk_frame.grid(row=r, column=1, columnspan=2, sticky="ew", **pad); r += 1

        # Weitere benutzerdefinierte Variablen
        ctk.CTkLabel(self, text="Weitere Vars:", anchor="w").grid(
            row=r, column=0, sticky="nw", **pad
        )
        self._extra_outer = ctk.CTkFrame(self, fg_color="transparent")
        self._extra_outer.grid(row=r, column=1, columnspan=2, sticky="ew", **pad)
        self._extra_outer.grid_columnconfigure(0, weight=1)
        self._extra_rows: list[tuple] = []
        self._extra_inner = ctk.CTkScrollableFrame(
            self._extra_outer, height=95, fg_color=("gray85", "gray17"),
        )
        self._extra_inner.pack(fill="x")
        self._extra_inner.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            self._extra_outer, text="＋ Variable hinzufügen", height=26,
            fg_color="gray40", hover_color="gray30",
            command=self._add_extra_row,
        ).pack(anchor="w", pady=(4, 0))
        r += 1

        # Buttons
        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=r, column=0, columnspan=3, pady=18)
        ctk.CTkButton(btn, text="Speichern", width=140, command=self._save).pack(
            side="left", padx=8
        )
        ctk.CTkButton(
            btn, text="Abbrechen", width=140, command=self.destroy,
            fg_color="gray40", hover_color="gray30",
        ).pack(side="left", padx=8)

        # Initiales Layout
        self._on_mode_change("📁  Lokaler Ordner")

    def _lbl_row(self, r: int, label: str, widget):
        ctk.CTkLabel(self, text=label, anchor="w").grid(
            row=r, column=0, sticky="w", padx=20, pady=5
        )
        widget.grid(row=r, column=1, columnspan=2, sticky="ew", padx=20, pady=5)

    # ── Modus-Wechsel ─────────────────────────────────────────────────────

    def _on_mode_change(self, value: str):
        is_local = "Lokaler" in value
        # Zeige/verstecke Quell-Zeilen
        if is_local:
            self._local_frame.grid()
            ctk.CTkLabel(self, text="Verzeichnis:", anchor="w").grid(
                row=self._local_row, column=0, sticky="w", padx=20, pady=5
            )
            self._git_frame.grid_remove()
        else:
            self._local_frame.grid_remove()
            self._git_frame.grid()
            ctk.CTkLabel(self, text="Repository:", anchor="w").grid(
                row=self._git_row, column=0, sticky="nw", padx=20, pady=5
            )

    # ── Browse-Buttons ────────────────────────────────────────────────────

    def _browse_local(self):
        path = filedialog.askdirectory(
            title="Django-Quellverzeichnis wählen", parent=self
        )
        if not path:
            return
        self.v_source.set(path)
        self._autofill_from_name(Path(path).name)
        self._autodetect_settings(Path(path))

    def _autodetect_settings(self, project_dir: Path):
        """Erkennt automatisch das Django-Settings-Modul und trägt es ein."""
        module = _detect_settings_module(project_dir)
        if module and self.v_settings_module.get() in ("", "core.settings"):
            self.v_settings_module.set(module)

    def _browse_ssh_key(self):
        path = filedialog.askopenfilename(
            title="Privaten SSH-Schlüssel wählen",
            filetypes=[
                ("Private Keys", "id_* *.pem *.rsa *.key"),
                ("Alle Dateien", "*"),
            ],
            initialdir=Path.home() / ".ssh",
            parent=self,
        )
        if path:
            self.v_ssh_key.set(path)

    def _open_ssh_manager(self):
        """Öffnet den SSH-Key-Manager; übernimmt den privaten Schlüsselpfad."""
        slug = _slug(self.v_name.get()) if self.v_name.get().strip() else "app"
        dlg = SshKeyDialog(self, app_slug=slug)
        self.wait_window(dlg)
        if dlg.result_priv_path:
            self.v_ssh_key.set(dlg.result_priv_path)

    def _autofill_from_name(self, name: str):
        """Füllt DB-Felder aus wenn noch leer."""
        sl = _slug(name)
        if not self.v_name.get():
            self.v_name.set(name)
        if not self.v_db_name.get():
            self.v_db_name.set(sl)
        if not self.v_db_user.get():
            self.v_db_user.set(sl)
        if not self.v_db_pass.get():
            self.v_db_pass.set(_random_password())

    def _add_extra_row(self, key: str = "", value: str = ""):
        """Fügt eine Zeile KEY=VALUE zur benutzerdefinierten Variablen-Tabelle hinzu."""
        row_frame = ctk.CTkFrame(self._extra_inner, fg_color="transparent")
        row_frame.pack(fill="x", padx=4, pady=2)
        row_frame.grid_columnconfigure(1, weight=1)
        k_var = ctk.StringVar(value=key)
        v_var = ctk.StringVar(value=value)
        ctk.CTkEntry(
            row_frame, textvariable=k_var, width=130,
            placeholder_text="SCHLÜSSEL",
        ).grid(row=0, column=0, padx=(0, 4))
        ctk.CTkEntry(
            row_frame, textvariable=v_var,
            placeholder_text="Wert",
        ).grid(row=0, column=1, sticky="ew", padx=(0, 4))

        def _remove(rf=row_frame):
            self._extra_rows = [(k, v, f) for k, v, f in self._extra_rows if f is not rf]
            rf.destroy()

        ctk.CTkButton(
            row_frame, text="−", width=28, height=28,
            fg_color="gray30", hover_color="#c0392b",
            command=_remove,
        ).grid(row=0, column=2)
        self._extra_rows.append((k_var, v_var, row_frame))

    # ── Befüllen bei Bearbeitung ──────────────────────────────────────────

    def _fill(self, app: dict):
        self.v_name.set(app.get("name", ""))
        self.v_port.set(str(app.get("port", 8000)))
        self.v_db_name.set(app.get("db_name", ""))
        self.v_db_user.set(app.get("db_user", ""))
        self.v_db_pass.set(app.get("db_password", ""))
        self.v_db_port.set(str(app.get("db_port", 5433)))

        mode = app.get("source_mode", "local")
        if mode == "github":
            self.v_mode.set("🐙  GitHub / Git")
            self._on_mode_change("🐙  GitHub / Git")
            self.v_repo_url.set(app.get("repo_url", ""))
            self.v_branch.set(app.get("repo_branch", "main"))
            self.v_ssh_key.set(app.get("ssh_key_path", ""))
        else:
            self.v_mode.set("📁  Lokaler Ordner")
            self._on_mode_change("📁  Lokaler Ordner")
            self.v_source.set(app.get("source_path", ""))

        # Umgebungsvariablen befüllen
        self.v_settings_module.set(app.get("settings_module", "core.settings"))
        self.v_allowed_hosts.set(app.get("allowed_hosts", "localhost,127.0.0.1"))
        self.v_secret_key.set(app.get("secret_key", ""))
        try:
            extra = json.loads(app.get("extra_env") or "{}")
            for k, v in extra.items():
                self._add_extra_row(k, str(v))
        except (json.JSONDecodeError, TypeError):
            pass

    # ── Speichern ─────────────────────────────────────────────────────────

    def _save(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror("Fehler", "Name darf nicht leer sein.", parent=self)
            return

        try:
            port    = int(self.v_port.get())
            db_port = int(self.v_db_port.get())
        except ValueError:
            messagebox.showerror("Fehler", "Ports müssen Zahlen sein.", parent=self)
            return

        is_github = "GitHub" in self.v_mode.get()

        if is_github:
            repo_url = self.v_repo_url.get().strip()
            if not repo_url:
                messagebox.showerror(
                    "Fehler", "Repository-URL darf nicht leer sein.", parent=self
                )
                return
            branch      = self.v_branch.get().strip() or "main"
            ssh_key     = self.v_ssh_key.get().strip()
            # Lokaler Klon-Pfad
            slug        = _slug(name)
            source_path = str(REPOS_DIR / slug)
            source_mode = "github"
        else:
            source = self.v_source.get().strip()
            if not source or not Path(source).exists():
                messagebox.showerror(
                    "Fehler", "Quellverzeichnis nicht gefunden.", parent=self
                )
                return
            repo_url    = ""
            branch      = "main"
            ssh_key     = ""
            source_path = source
            source_mode = "local"

        # Extra-Variablen einlesen (leere Keys ignorieren)
        extra = {
            k.get().strip(): v.get()
            for k, v, _ in self._extra_rows
            if k.get().strip()
        }

        sl = _slug(name)
        self.result = {
            "name":            name,
            "source_path":     source_path,
            "port":            port,
            "db_name":         self.v_db_name.get().strip() or sl,
            "db_user":         self.v_db_user.get().strip() or sl,
            "db_password":     self.v_db_pass.get() or _random_password(),
            "db_port":         db_port,
            "source_mode":     source_mode,
            "repo_url":        repo_url,
            "repo_branch":     branch,
            "ssh_key_path":    ssh_key,
            "settings_module": self.v_settings_module.get().strip() or "core.settings",
            "allowed_hosts":   self.v_allowed_hosts.get().strip() or "localhost,127.0.0.1",
            "secret_key":      self.v_secret_key.get().strip(),
            "extra_env":       json.dumps(extra),
        }
        self.destroy()


# ─── Haupt-Fenster ────────────────────────────────────────────────────────────

class PortableDjangoManager(ctk.CTk):
    """Hauptfenster des Portable Django Managers."""

    def __init__(self):
        super().__init__()
        self.title("Portable Django Manager")
        self.geometry("1080x700")
        self.minsize(860, 560)

        self.db      = Database()
        self.git     = GitManager(log_callback=self._log_thread_safe)
        self.runners: dict[int, AppRunner] = {}

        self._build_ui()
        self._check_git()
        self._refresh()

    # ─── UI-Aufbau ────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Sidebar ───────────────────────────────────────────────────────
        sidebar = ctk.CTkFrame(self, width=215, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)
        sidebar.grid_rowconfigure(10, weight=1)

        ctk.CTkLabel(
            sidebar,
            text="Portable\nDjango Manager",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).grid(row=0, column=0, padx=20, pady=(24, 16), sticky="w")

        ctk.CTkButton(
            sidebar, text="＋  App hinzufügen",
            command=self._add_app,
        ).grid(row=1, column=0, padx=14, pady=4, sticky="ew")

        ctk.CTkButton(
            sidebar, text="⏹  Alle stoppen",
            fg_color="gray40", hover_color="gray30",
            command=self._stop_all,
        ).grid(row=2, column=0, padx=14, pady=4, sticky="ew")

        ctk.CTkFrame(sidebar, height=1, fg_color="gray30").grid(
            row=3, column=0, sticky="ew", padx=14, pady=12
        )

        # Git-Status
        self._git_label = ctk.CTkLabel(
            sidebar,
            text="Git: prüfe …",
            text_color="gray55",
            font=ctk.CTkFont(size=11),
        )
        self._git_label.grid(row=4, column=0, padx=14, sticky="w")

        # Info-Kasten
        info = ctk.CTkFrame(sidebar, fg_color=("gray85", "gray20"))
        info.grid(row=5, column=0, padx=14, pady=12, sticky="ew")
        ctk.CTkLabel(
            info,
            text="python/  und  postgres/\nmüssen im Tool-Ordner\nvorhanden sein.\n\n→ setup_environment.ps1",
            text_color="gray55",
            font=ctk.CTkFont(size=11),
            justify="left",
        ).pack(padx=10, pady=10, anchor="w")

        # About-Button
        ctk.CTkButton(
            sidebar, text="ℹ  Über / About",
            height=30,
            fg_color="transparent",
            border_width=1,
            border_color=("gray70", "gray35"),
            text_color=("gray30", "gray70"),
            hover_color=("gray85", "gray25"),
            font=ctk.CTkFont(size=12),
            command=self._show_about,
        ).grid(row=9, column=0, padx=14, pady=(0, 6), sticky="ew")

        # Pink-Elefant-Signatur am Seitenleisten-Fuß
        sig = ctk.CTkFrame(sidebar, fg_color=("gray85", "#111111"), corner_radius=10)
        sig.grid(row=11, column=0, padx=14, pady=(0, 14), sticky="ew")
        sig.grid_columnconfigure(0, weight=1)

        sig_cv = tk.Canvas(sig, width=56, height=46,
                           bg="#111111", highlightthickness=0)
        sig_cv.grid(row=0, column=0, pady=(10, 2))
        _draw_elephant(sig_cv, ox=1, oy=1, scale=0.58)

        ctk.CTkLabel(
            sig, text="PINK ELEFANT",
            font=ctk.CTkFont(family="Arial", size=11, weight="bold"),
            text_color=PINK,
            fg_color="#111111",
        ).grid(row=1, column=0, pady=(0, 2))

        ctk.CTkLabel(
            sig, text="v1.1",
            font=ctk.CTkFont(size=9),
            text_color="gray50",
            fg_color="#111111",
        ).grid(row=2, column=0, pady=(0, 8))

        # ── Inhaltsbereich ────────────────────────────────────────────────
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            content,
            text="Meine Web-Apps",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 8))

        self.app_list_frame = ctk.CTkScrollableFrame(content)
        self.app_list_frame.grid(
            row=1, column=0, sticky="nsew", padx=16, pady=(0, 8)
        )
        self.app_list_frame.grid_columnconfigure(0, weight=1)

        # Log
        log_outer = ctk.CTkFrame(content)
        log_outer.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        log_outer.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(log_outer, text="Ausgabe", anchor="w",
                     font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(8, 0)
        )
        self._log_box = ctk.CTkTextbox(log_outer, height=150, wrap="word")
        self._log_box.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 10))
        self._log_box.configure(state="disabled")

    # ─── App-Liste rendern ────────────────────────────────────────────────

    def _refresh(self):
        for w in self.app_list_frame.winfo_children():
            w.destroy()

        apps = self.db.get_apps()
        if not apps:
            ctk.CTkLabel(
                self.app_list_frame,
                text="Noch keine Apps konfiguriert.\nKlicken Sie auf '＋ App hinzufügen'.",
                text_color="gray60",
                font=ctk.CTkFont(size=13),
            ).pack(pady=60)
            return

        for app in apps:
            self._render_row(app)

    def _render_row(self, app: dict):
        running    = self._is_running(app["id"])
        is_github  = app.get("source_mode", "local") == "github"
        dot        = "●" if running else "○"
        dot_color  = "#2ecc71" if running else "#e74c3c"

        card = ctk.CTkFrame(self.app_list_frame, corner_radius=10)
        card.pack(fill="x", padx=4, pady=5)
        card.grid_columnconfigure(1, weight=1)

        # Status-Punkt
        ctk.CTkLabel(
            card, text=dot, text_color=dot_color,
            font=ctk.CTkFont(size=20),
        ).grid(row=0, column=0, padx=(14, 4), pady=12)

        # App-Info
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.grid(row=0, column=1, sticky="w", pady=10)

        # Titelzeile
        title_row = ctk.CTkFrame(info, fg_color="transparent")
        title_row.pack(anchor="w")
        ctk.CTkLabel(
            title_row, text=app["name"],
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(side="left")
        if is_github:
            ctk.CTkLabel(
                title_row,
                text="  🐙 GitHub",
                text_color="#3498db",
                font=ctk.CTkFont(size=11),
            ).pack(side="left")

        # Detailzeile
        if is_github:
            url   = app.get("repo_url", "")
            short = url.replace("https://github.com/", "").replace("git@github.com:", "")
            branch = app.get("repo_branch", "main")
            detail = f"⎇ {branch}  ·  {short}  ·  Port {app['port']}  ·  DB: {app['db_name']}"
        else:
            detail = (
                f"📁 {app['source_path']}  ·  Port {app['port']}  ·  DB: {app['db_name']}"
            )
        ctk.CTkLabel(
            info, text=detail, text_color="gray55",
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w")

        # Aktions-Buttons
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.grid(row=0, column=2, padx=10)

        if running:
            ctk.CTkButton(
                btns, text="⏹ Stop", width=86,
                fg_color="#c0392b", hover_color="#962d22",
                command=lambda a=app: self._stop_app(a),
            ).pack(side="left", padx=2)
            ctk.CTkButton(
                btns, text="🌐", width=42,
                command=lambda a=app: self._open_browser(a),
            ).pack(side="left", padx=2)
        else:
            ctk.CTkButton(
                btns, text="▶ Start", width=86,
                fg_color="#27ae60", hover_color="#1e8449",
                command=lambda a=app: self._start_app(a),
            ).pack(side="left", padx=2)

        if is_github:
            ctk.CTkButton(
                btns, text="⬆ Update", width=86,
                fg_color="#2980b9", hover_color="#1a6fa1",
                command=lambda a=app: self._update_repo(a),
            ).pack(side="left", padx=2)

        # Superuser-Button (nur wenn initdb bereits gelaufen ist)
        app_data_dir = BASE_DIR / "data" / f"app_{app['id']}"
        if (app_data_dir / "PG_VERSION").exists():
            ctk.CTkButton(
                btns, text="👤", width=36,
                fg_color="gray40", hover_color="#8e44ad",
                command=lambda a=app: self._create_superuser(a),
            ).pack(side="left", padx=2)

        ctk.CTkButton(
            btns, text="✏", width=36,
            fg_color="gray40", hover_color="gray30",
            command=lambda a=app: self._edit_app(a),
        ).pack(side="left", padx=2)
        ctk.CTkButton(
            btns, text="🗑", width=36,
            fg_color="gray30", hover_color="gray20",
            command=lambda a=app: self._delete_app(a),
        ).pack(side="left", padx=2)

    # ─── App-Aktionen ─────────────────────────────────────────────────────

    def _add_app(self):
        dlg = AppDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return

        result = dlg.result
        is_github = result.get("source_mode") == "github"

        # Bei GitHub: sofort klonen
        if is_github:
            self._log(f"🐙 Klone Repository für '{result['name']}' …")
            ok = self.git.clone(
                url=result["repo_url"],
                dest=Path(result["source_path"]),
                branch=result["repo_branch"],
                ssh_key_path=result.get("ssh_key_path") or None,
            )
            if not ok:
                messagebox.showerror(
                    "Git-Fehler",
                    "Repository konnte nicht geklont werden.\n"
                    "Prüfen Sie URL und SSH-Schlüssel (Details im Log).",
                    parent=self,
                )
                return
            # Settings-Modul aus geklontem Repo erkennen (falls noch Standard)
            if result.get("settings_module") in ("", "core.settings"):
                detected = _detect_settings_module(Path(result["source_path"]))
                if detected:
                    result["settings_module"] = detected
                    self._log(f"  Settings-Modul erkannt: {detected}")

        self.db.add_app(**result)
        self._log(f"App '{result['name']}' hinzugefügt.")
        self._refresh()

    def _edit_app(self, app: dict):
        dlg = AppDialog(self, app=app)
        self.wait_window(dlg)
        if dlg.result:
            self.db.update_app(app["id"], **dlg.result)
            self._log(f"App '{dlg.result['name']}' gespeichert.")
            self._refresh()

    def _delete_app(self, app: dict):
        if self._is_running(app["id"]):
            messagebox.showwarning(
                "Laufende App", "Bitte zuerst die App stoppen.", parent=self
            )
            return
        if messagebox.askyesno(
            "Löschen",
            f"App '{app['name']}' wirklich entfernen?\n"
            "(Quellcode und Datenbankdaten werden NICHT gelöscht.)",
            parent=self,
        ):
            self.db.delete_app(app["id"])
            self._log(f"App '{app['name']}' entfernt.")
            self._refresh()

    def _start_app(self, app: dict):
        if self._is_running(app["id"]):
            return
        runner = AppRunner(
            app, base_dir=BASE_DIR, log_callback=self._log_thread_safe
        )
        self.runners[app["id"]] = runner
        self._log(f"▶ Starte '{app['name']}' …")
        self._refresh()

        def on_done(ok: bool):
            self.after(0, self._refresh)
            if ok:
                self.after(2500, lambda: self._open_browser(app))

        runner.start(on_complete=on_done)

    def _stop_app(self, app: dict):
        runner = self.runners.pop(app["id"], None)
        if runner:
            threading.Thread(target=runner.stop, daemon=True).start()
        self._log(f"⏹ Stoppe '{app['name']}' …")
        self.after(1200, self._refresh)

    def _stop_all(self):
        for runner in list(self.runners.values()):
            threading.Thread(target=runner.stop, daemon=True).start()
        self.runners.clear()
        self._log("⏹ Alle Apps gestoppt.")
        self.after(1500, self._refresh)

    def _open_browser(self, app: dict):
        webbrowser.open(f"http://localhost:{app['port']}")

    def _show_about(self):
        AboutDialog(self)

    def _create_superuser(self, app: dict):
        dlg = SuperuserDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return
        d = dlg.result
        # Temporären Runner nutzen (oder laufenden, falls vorhanden)
        runner = self.runners.get(app["id"]) or AppRunner(
            app, base_dir=BASE_DIR, log_callback=self._log_thread_safe
        )
        self._log(f"👤 Erstelle Superuser '{d['username']}' für '{app['name']}' …")

        def _run():
            ok, msg = runner.create_superuser(d["username"], d["email"], d["password"])
            symbol = "✅" if ok else "❌"
            self._log_thread_safe(f"  {symbol} {msg}")
            if ok:
                self.after(0, lambda: messagebox.showinfo("Superuser", msg, parent=self))
            else:
                self.after(0, lambda: messagebox.showerror("Fehler", msg, parent=self))

        threading.Thread(target=_run, daemon=True).start()

    # ─── GitHub Update ────────────────────────────────────────────────────

    def _update_repo(self, app: dict):
        """Zieht die neueste Version aus dem Repository und führt Migrationen aus."""
        if self._is_running(app["id"]):
            messagebox.showwarning(
                "App läuft",
                "Bitte zuerst die App stoppen, dann aktualisieren.",
                parent=self,
            )
            return

        self._log(f"⬆ Aktualisiere '{app['name']}' …")

        def _do_update():
            repo_path   = Path(app["source_path"])
            ssh_key     = app.get("ssh_key_path") or None
            branch      = app.get("repo_branch", "main")

            if not self.git.is_cloned(repo_path):
                self._log_thread_safe("  Kein lokaler Klon gefunden – klone neu …")
                ok = self.git.clone(
                    url=app["repo_url"],
                    dest=repo_path,
                    branch=branch,
                    ssh_key_path=ssh_key,
                )
            else:
                ok = self.git.pull(repo_path, branch=branch, ssh_key_path=ssh_key)

            if not ok:
                self._log_thread_safe(f"  FEHLER beim Git-Update für '{app['name']}'.")
                return

            # Migrationen ausführen wenn Datenbank bereits eingerichtet
            data_dir = BASE_DIR / "data" / f"app_{app['id']}" / "PG_VERSION"
            if data_dir.exists():
                self._log_thread_safe("  Führe Django-Migrationen aus …")
                runner = AppRunner(
                    app, base_dir=BASE_DIR,
                    log_callback=self._log_thread_safe,
                )
                runner._run_migrations()

            commit = self.git.current_commit(repo_path)
            self._log_thread_safe(
                f"  '{app['name']}' aktualisiert  →  Commit {commit}"
            )

        threading.Thread(target=_do_update, daemon=True).start()

    # ─── Git-Status prüfen ────────────────────────────────────────────────

    def _check_git(self):
        def _check():
            if self.git.is_available():
                ver = self.git.get_git_version()
                self.after(0, lambda: self._git_label.configure(
                    text=f"Git: ✓ {ver.replace('git version ', '')}",
                    text_color="#2ecc71",
                ))
            else:
                self.after(0, lambda: self._git_label.configure(
                    text="Git: ✗ nicht gefunden",
                    text_color="#e74c3c",
                ))

        threading.Thread(target=_check, daemon=True).start()

    # ─── Hilfsmethoden ────────────────────────────────────────────────────

    def _is_running(self, app_id: int) -> bool:
        r = self.runners.get(app_id)
        return r is not None and r.is_running()

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._log_box.configure(state="normal")
        self._log_box.insert("end", f"[{ts}] {msg}\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _log_thread_safe(self, msg: str):
        self.after(0, lambda: self._log(msg))

    # ─── Fenster schließen ────────────────────────────────────────────────

    def on_close(self):
        if any(r.is_running() for r in self.runners.values()):
            if not messagebox.askyesno(
                "Beenden",
                "Laufende Apps stoppen und Programm beenden?",
                parent=self,
            ):
                return
            self._stop_all()
            self.after(1800, self.destroy)
        else:
            self.destroy()


# ─── Einstiegspunkt ──────────────────────────────────────────────────────────

def main():
    app = PortableDjangoManager()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()
