"""
Portable Django Tester  –  Grafisches Verwaltungs-Tool
======================================================
Verwaltet mehrere Django-Webanwendungen mit eingebettetem Python
und portatiblem PostgreSQL auf einem Windows-Rechner.

Benötigt:  pip install customtkinter
Paketieren: build_exe.bat  (erzeugt portable .exe via PyInstaller)
"""

import secrets
import string
import threading
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from db import Database
from runner import AppRunner, BASE_DIR

# ─── Erscheinungsbild ─────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


# ─── Hilfsfunktion ───────────────────────────────────────────────────────────

def _random_password(length: int = 20) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


# ─── App-Dialog (Hinzufügen / Bearbeiten) ────────────────────────────────────

class AppDialog(ctk.CTkToplevel):
    """Modaler Dialog zum Anlegen oder Bearbeiten einer App-Konfiguration."""

    def __init__(self, parent, app: dict | None = None):
        super().__init__(parent)
        self.app = app
        self.result: dict | None = None

        self.title("App bearbeiten" if app else "Neue App hinzufügen")
        self.geometry("520x500")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()
        self.lift()

        self._build()
        if app:
            self._fill(app)

    # ── Layout ────────────────────────────────────────────────────────────

    def _build(self):
        pad = {"padx": 20, "pady": 6}
        self.grid_columnconfigure(1, weight=1)

        row = 0
        ctk.CTkLabel(
            self,
            text="App-Konfiguration",
            font=ctk.CTkFont(size=16, weight="bold"),
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=20, pady=(18, 10))
        row += 1

        # Name
        self.v_name = ctk.StringVar()
        self._row(row, "Name:", ctk.CTkEntry(self, textvariable=self.v_name)); row += 1

        # Quellverzeichnis + Browse-Button
        self.v_source = ctk.StringVar()
        src_frame = ctk.CTkFrame(self, fg_color="transparent")
        src_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(src_frame, textvariable=self.v_source).grid(
            row=0, column=0, sticky="ew"
        )
        ctk.CTkButton(
            src_frame, text="…", width=36, command=self._browse
        ).grid(row=0, column=1, padx=(6, 0))
        ctk.CTkLabel(self, text="Quellverzeichnis:", anchor="w").grid(
            row=row, column=0, sticky="w", **pad
        )
        src_frame.grid(row=row, column=1, columnspan=2, sticky="ew", **pad)
        row += 1

        # Port
        self.v_port = ctk.StringVar(value="8000")
        self._row(row, "App-Port:", ctk.CTkEntry(self, textvariable=self.v_port, width=100)); row += 1

        # Trennlinie
        ctk.CTkFrame(self, height=1, fg_color="gray30").grid(
            row=row, column=0, columnspan=3, sticky="ew", padx=20, pady=6
        ); row += 1
        ctk.CTkLabel(
            self, text="Datenbank", font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=row, column=0, columnspan=3, sticky="w", padx=20); row += 1

        # DB-Felder
        self.v_db_name = ctk.StringVar()
        self._row(row, "Datenbankname:", ctk.CTkEntry(self, textvariable=self.v_db_name)); row += 1

        self.v_db_user = ctk.StringVar()
        self._row(row, "DB-Benutzer:", ctk.CTkEntry(self, textvariable=self.v_db_user)); row += 1

        self.v_db_pass = ctk.StringVar()
        pw_frame = ctk.CTkFrame(self, fg_color="transparent")
        pw_frame.grid_columnconfigure(0, weight=1)
        self._pw_entry = ctk.CTkEntry(
            pw_frame, textvariable=self.v_db_pass, show="●"
        )
        self._pw_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            pw_frame, text="⟳", width=36,
            command=lambda: self.v_db_pass.set(_random_password()),
        ).grid(row=0, column=1, padx=(6, 0))
        ctk.CTkLabel(self, text="DB-Passwort:", anchor="w").grid(
            row=row, column=0, sticky="w", **pad
        )
        pw_frame.grid(row=row, column=1, columnspan=2, sticky="ew", **pad); row += 1

        self.v_db_port = ctk.StringVar(value="5433")
        self._row(row, "DB-Port:", ctk.CTkEntry(self, textvariable=self.v_db_port, width=100)); row += 1

        # Buttons
        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=row, column=0, columnspan=3, pady=18)
        ctk.CTkButton(btn, text="Speichern", width=130, command=self._save).pack(
            side="left", padx=8
        )
        ctk.CTkButton(
            btn, text="Abbrechen", width=130, command=self.destroy,
            fg_color="gray40", hover_color="gray30",
        ).pack(side="left", padx=8)

    def _row(self, r: int, label: str, widget):
        ctk.CTkLabel(self, text=label, anchor="w").grid(
            row=r, column=0, sticky="w", padx=20, pady=6
        )
        widget.grid(row=r, column=1, columnspan=2, sticky="ew", padx=20, pady=6)

    # ── Logik ─────────────────────────────────────────────────────────────

    def _browse(self):
        path = filedialog.askdirectory(
            title="Django-Quellverzeichnis wählen", parent=self
        )
        if not path:
            return
        self.v_source.set(path)
        if not self.v_name.get():
            self.v_name.set(Path(path).name)
        slug = Path(path).name.lower().replace("-", "_").replace(" ", "_")
        if not self.v_db_name.get():
            self.v_db_name.set(slug)
        if not self.v_db_user.get():
            self.v_db_user.set(slug)
        if not self.v_db_pass.get():
            self.v_db_pass.set(_random_password())

    def _fill(self, app: dict):
        self.v_name.set(app.get("name", ""))
        self.v_source.set(app.get("source_path", ""))
        self.v_port.set(str(app.get("port", 8000)))
        self.v_db_name.set(app.get("db_name", ""))
        self.v_db_user.set(app.get("db_user", ""))
        self.v_db_pass.set(app.get("db_password", ""))
        self.v_db_port.set(str(app.get("db_port", 5433)))

    def _save(self):
        name   = self.v_name.get().strip()
        source = self.v_source.get().strip()
        if not name:
            messagebox.showerror("Fehler", "Name darf nicht leer sein.", parent=self)
            return
        if not source or not Path(source).exists():
            messagebox.showerror("Fehler", "Quellverzeichnis nicht gefunden.", parent=self)
            return
        try:
            port    = int(self.v_port.get())
            db_port = int(self.v_db_port.get())
        except ValueError:
            messagebox.showerror("Fehler", "Ports müssen Zahlen sein.", parent=self)
            return

        slug = name.lower().replace(" ", "_")
        self.result = {
            "name":        name,
            "source_path": source,
            "port":        port,
            "db_name":     self.v_db_name.get().strip() or slug,
            "db_user":     self.v_db_user.get().strip() or slug,
            "db_password": self.v_db_pass.get() or _random_password(),
            "db_port":     db_port,
        }
        self.destroy()


# ─── Haupt-Fenster ────────────────────────────────────────────────────────────

class PortableDjangoManager(ctk.CTk):
    """Hauptfenster des Portable Django Testers."""

    def __init__(self):
        super().__init__()
        self.title("Portable Django Tester")
        self.geometry("1040x700")
        self.minsize(820, 560)

        self.db      = Database()
        self.runners: dict[int, AppRunner] = {}   # app_id → AppRunner

        self._build_ui()
        self._refresh()

    # ─── UI-Aufbau ────────────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ── Sidebar ───────────────────────────────────────────────────────
        sidebar = ctk.CTkFrame(self, width=210, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(8, weight=1)

        ctk.CTkLabel(
            sidebar,
            text="Portable\nDjango Tester",
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

        # Info-Kasten
        info = ctk.CTkFrame(sidebar, fg_color=("gray85", "gray20"))
        info.grid(row=4, column=0, padx=14, pady=4, sticky="ew")
        ctk.CTkLabel(
            info, text="Portable Python + PostgreSQL\nwerden im Ordner\n'python/' und 'postgres/'\nerwartet.",
            text_color="gray60",
            font=ctk.CTkFont(size=11),
            justify="left",
        ).pack(padx=10, pady=10, anchor="w")

        ctk.CTkLabel(sidebar, text="v1.0", text_color="gray50",
                     font=ctk.CTkFont(size=11)).grid(
            row=9, column=0, pady=12
        )

        # ── Inhaltsbereich ────────────────────────────────────────────────
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=1, sticky="nsew")
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(1, weight=1)

        # Überschrift
        ctk.CTkLabel(
            content,
            text="Meine Web-Apps",
            font=ctk.CTkFont(size=20, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(20, 8))

        # App-Liste (scrollbar)
        self.app_list_frame = ctk.CTkScrollableFrame(content)
        self.app_list_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 8))
        self.app_list_frame.grid_columnconfigure(0, weight=1)

        # Ausgabe-Log
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
        running = self._is_running(app["id"])
        dot     = "●" if running else "○"
        dot_color = "#2ecc71" if running else "#e74c3c"

        card = ctk.CTkFrame(self.app_list_frame, corner_radius=10)
        card.pack(fill="x", padx=4, pady=5)
        card.grid_columnconfigure(1, weight=1)

        # Status-Punkt
        ctk.CTkLabel(card, text=dot, text_color=dot_color,
                     font=ctk.CTkFont(size=20)).grid(
            row=0, column=0, padx=(14, 6), pady=14
        )

        # App-Info
        info = ctk.CTkFrame(card, fg_color="transparent")
        info.grid(row=0, column=1, sticky="w", pady=10)
        ctk.CTkLabel(
            info, text=app["name"],
            font=ctk.CTkFont(size=14, weight="bold"),
        ).pack(anchor="w")
        ctk.CTkLabel(
            info,
            text=(
                f"Port {app['port']}  ·  DB: {app['db_name']} "
                f"(:{app['db_port']})  ·  {app['source_path']}"
            ),
            text_color="gray55",
            font=ctk.CTkFont(size=11),
        ).pack(anchor="w")

        # Aktions-Buttons
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.grid(row=0, column=2, padx=12)

        if running:
            ctk.CTkButton(
                btns, text="⏹ Stop", width=86,
                fg_color="#c0392b", hover_color="#962d22",
                command=lambda a=app: self._stop_app(a),
            ).pack(side="left", padx=3)
            ctk.CTkButton(
                btns, text="🌐 Browser", width=90,
                command=lambda a=app: self._open_browser(a),
            ).pack(side="left", padx=3)
        else:
            ctk.CTkButton(
                btns, text="▶ Start", width=86,
                fg_color="#27ae60", hover_color="#1e8449",
                command=lambda a=app: self._start_app(a),
            ).pack(side="left", padx=3)

        ctk.CTkButton(
            btns, text="✏", width=38,
            fg_color="gray40", hover_color="gray30",
            command=lambda a=app: self._edit_app(a),
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            btns, text="🗑", width=38,
            fg_color="gray30", hover_color="gray20",
            command=lambda a=app: self._delete_app(a),
        ).pack(side="left", padx=3)

    # ─── App-Aktionen ─────────────────────────────────────────────────────

    def _add_app(self):
        dlg = AppDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self.db.add_app(**dlg.result)
            self._log(f"App '{dlg.result['name']}' hinzugefügt.")
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
                "Laufende App",
                "Bitte zuerst die App stoppen.", parent=self
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
        runner = AppRunner(app, base_dir=BASE_DIR, log_callback=self._log_thread_safe)
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
        for rid, runner in list(self.runners.items()):
            threading.Thread(target=runner.stop, daemon=True).start()
        self.runners.clear()
        self._log("⏹ Alle Apps gestoppt.")
        self.after(1500, self._refresh)

    def _open_browser(self, app: dict):
        webbrowser.open(f"http://localhost:{app['port']}")

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
