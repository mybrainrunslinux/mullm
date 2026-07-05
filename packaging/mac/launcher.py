#!/usr/bin/env python3
"""
muLLM Mac Launcher — bootstraps the full stack with a native-looking GUI.

Packed with PyInstaller (--onefile --windowed) so the user double-clicks
muLLM.app and sees a progress window, not a terminal.

Branding: amber #f59e0b on slate #0f172a  (matches the web UI)
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import messagebox, ttk

    HAS_TK = True
except ImportError:
    HAS_TK = False

# ── Constants ──────────────────────────────────────────────────────────────────
MULLM_VERSION = "0.9.9"
MULLM_PORT = 6856
MULLM_URL = f"http://localhost:{MULLM_PORT}"
SETUP_URL = f"{MULLM_URL}/setup"

# Branding colours
BG_DARK = "#0f172a"       # slate-900
BG_CARD = "#1e293b"       # slate-800
AMBER = "#f59e0b"         # amber-400
AMBER_DARK = "#d97706"    # amber-500
TEXT_WHITE = "#f8fafc"    # slate-50
TEXT_MUTED = "#94a3b8"    # slate-400
GREEN = "#22c55e"         # green-500
RED = "#ef4444"           # red-500


# ── GUI launcher ──────────────────────────────────────────────────────────────
class BootstrapUI:
    """Full tkinter progress window with amber/slate branding."""

    def __init__(self):
        if not HAS_TK:
            self._run_headless()
            return

        self.root = tk.Tk()
        self.root.title("muLLM")
        self.root.geometry("500x320")
        self.root.resizable(False, False)
        self.root.configure(bg=BG_DARK)
        # Centre on screen
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - 500) // 2
        y = (sh - 320) // 2
        self.root.geometry(f"500x320+{x}+{y}")

        self._build_ui()
        # Run bootstrap in a background thread so the GUI stays responsive
        t = threading.Thread(target=self._run_steps, daemon=True)
        t.start()
        self.root.mainloop()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        # Header bar
        header = tk.Frame(self.root, bg=AMBER, height=4)
        header.pack(fill="x", side="top")

        # Logo / title row
        title_frame = tk.Frame(self.root, bg=BG_DARK, pady=18)
        title_frame.pack(fill="x")

        tk.Label(
            title_frame,
            text="μ|LLM",
            font=("Helvetica", 28, "bold"),
            fg=AMBER,
            bg=BG_DARK,
        ).pack()

        tk.Label(
            title_frame,
            text="Local-first AI router",
            font=("Helvetica", 11),
            fg=TEXT_MUTED,
            bg=BG_DARK,
        ).pack()

        # Status label
        self.status_var = tk.StringVar(value="Starting up…")
        self.status_label = tk.Label(
            self.root,
            textvariable=self.status_var,
            font=("Helvetica", 11),
            fg=TEXT_WHITE,
            bg=BG_DARK,
            wraplength=460,
        )
        self.status_label.pack(pady=(0, 8))

        # Progress bar — styled amber
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Amber.Horizontal.TProgressbar",
            troughcolor=BG_CARD,
            background=AMBER,
            bordercolor=BG_CARD,
            lightcolor=AMBER,
            darkcolor=AMBER_DARK,
        )

        self.progress = ttk.Progressbar(
            self.root,
            style="Amber.Horizontal.TProgressbar",
            length=420,
            mode="determinate",
            maximum=100,
        )
        self.progress.pack(pady=(0, 12))

        # Log area (scrollable text)
        log_frame = tk.Frame(self.root, bg=BG_CARD, padx=8, pady=6)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self.log_text = tk.Text(
            log_frame,
            height=6,
            font=("Courier", 9),
            fg=TEXT_MUTED,
            bg=BG_CARD,
            insertbackground=AMBER,
            relief="flat",
            wrap="word",
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)

    def _log(self, msg: str):
        """Append a line to the log area (thread-safe)."""
        def _append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"{msg}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")

        if HAS_TK and hasattr(self, "root"):
            try:
                self.root.after(0, _append)
            except Exception:
                pass
        else:
            print(f"[muLLM] {msg}")

    def _set_status(self, msg: str, pct: int):
        """Update status label and progress bar (thread-safe)."""
        def _update():
            self.status_var.set(msg)
            self.progress["value"] = pct

        if HAS_TK and hasattr(self, "root"):
            try:
                self.root.after(0, _update)
            except Exception:
                pass

    def _finish_success(self):
        """Close the window and open the browser."""
        def _close():
            webbrowser.open(SETUP_URL)
            self.root.destroy()

        if HAS_TK and hasattr(self, "root"):
            self.root.after(1500, _close)

    def _finish_error(self, msg: str):
        """Show error dialog and exit."""
        def _show():
            messagebox.showerror("muLLM Setup Failed", msg)
            self.root.destroy()
            sys.exit(1)

        if HAS_TK and hasattr(self, "root"):
            self.root.after(0, _show)

    # ── Bootstrap steps ───────────────────────────────────────────────────────

    def _run_steps(self):
        steps = [
            (10, "Checking Python version…",         self._check_python),
            (30, "Installing muLLM…",                self._install_mullm),
            (55, "Detecting GPU / metal backend…",   self._detect_gpu),
            (75, "Checking Ollama…",                 self._check_ollama),
            (90, "Starting muLLM server…",           self._start_server),
            (100, "Ready! Opening browser…",         lambda: None),
        ]
        for pct, label, fn in steps:
            self._set_status(label, pct)
            self._log(label)
            try:
                fn()
            except SystemExit:
                raise
            except Exception as exc:
                self._log(f"  ERROR: {exc}")
                self._finish_error(str(exc))
                return

        self._log("muLLM is running. Opening your browser…")
        self._finish_success()

    def _check_python(self):
        v = sys.version_info
        self._log(f"  Python {v.major}.{v.minor}.{v.micro}")
        if v < (3, 11):
            msg = (
                f"muLLM requires Python 3.11 or later.\n"
                f"You have Python {v.major}.{v.minor}.\n\n"
                "Install Python 3.11+ from https://python.org/downloads/\n"
                "or via Homebrew:  brew install python@3.11"
            )
            raise RuntimeError(msg)

    def _install_mullm(self):
        """Install or upgrade mullm from PyPI (or bundled wheel)."""
        # Check if already installed at correct version
        try:
            import importlib.metadata
            installed = importlib.metadata.version("mullm")
            self._log(f"  mullm {installed} already installed")
            if installed == MULLM_VERSION:
                return
            self._log(f"  Upgrading to {MULLM_VERSION}…")
        except Exception:
            self._log("  mullm not found — installing…")

        # Look for a bundled wheel alongside this launcher
        launcher_dir = Path(sys.executable).parent
        wheels = list(launcher_dir.glob(f"mullm-{MULLM_VERSION}*.whl"))
        if not wheels:
            wheels = list(Path(".").glob(f"mullm-{MULLM_VERSION}*.whl"))

        if wheels:
            self._log(f"  Installing from bundled wheel: {wheels[0].name}")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", str(wheels[0]), "--quiet"],
                timeout=120,
            )
        else:
            self._log("  Downloading from PyPI…")
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install",
                 f"mullm=={MULLM_VERSION}", "--quiet"],
                timeout=300,
            )

    def _detect_gpu(self):
        """Install the correct ML backend for this Mac."""
        machine = platform.machine()
        self._log(f"  Architecture: {machine}")

        if machine == "arm64":
            # Apple Silicon — use MLX (Apple's native ML framework)
            self._log("  Apple Silicon detected — checking MLX…")
            try:
                import mlx  # noqa: F401
                self._log("  MLX already installed")
            except ImportError:
                self._log("  Installing mlx-lm for Apple Silicon…")
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", "mlx-lm", "--quiet"],
                    timeout=300,
                )
        else:
            # Intel Mac — use llama.cpp (CPU/Metal)
            self._log("  Intel Mac detected — checking llama-cpp-python…")
            try:
                import llama_cpp  # noqa: F401
                self._log("  llama-cpp-python already installed")
            except ImportError:
                self._log("  Installing llama-cpp-python (Metal accelerated)…")
                env = os.environ.copy()
                env["CMAKE_ARGS"] = "-DLLAMA_METAL=on"
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install",
                     "llama-cpp-python", "--quiet"],
                    env=env,
                    timeout=600,
                )

    def _check_ollama(self):
        """Check for Ollama; offer to install if missing."""
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True, timeout=5,
            )
            if result.returncode == 0:
                self._log("  Ollama found and running")
                return
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        self._log("  Ollama not found")
        if HAS_TK:
            install_it = messagebox.askyesno(
                "Install Ollama?",
                "Ollama is not installed.\n\n"
                "muLLM uses Ollama to run local AI models.\n\n"
                "Install it now via Homebrew? (requires ~500MB download)\n\n"
                "You can skip this and add API keys instead.",
            )
            if install_it:
                self._log("  Installing Ollama via Homebrew…")
                subprocess.check_call(["brew", "install", "ollama"], timeout=300)
                subprocess.Popen(["ollama", "serve"])
                time.sleep(2)
                self._log("  Ollama installed and started")
            else:
                self._log("  Skipping Ollama — you can install it later at https://ollama.ai")
        else:
            print(
                "[muLLM] Ollama not found. Install from https://ollama.ai "
                "or run:  brew install ollama"
            )

    def _start_server(self):
        """Launch the muLLM FastAPI server in the background."""
        import socket

        # Check if already listening on the port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", MULLM_PORT)) == 0:
                self._log(f"  Server already running on port {MULLM_PORT}")
                return

        self._log(f"  Starting muLLM server on port {MULLM_PORT}…")

        # Write a persistent shell wrapper to ~/Applications/muLLM/run.sh
        app_dir = Path.home() / "Applications" / "muLLM"
        app_dir.mkdir(parents=True, exist_ok=True)
        wrapper = app_dir / "run.sh"
        wrapper.write_text(
            f"#!/bin/bash\n"
            f'exec "{sys.executable}" -m router.main\n'
        )
        wrapper.chmod(0o755)

        # Start the server
        log_path = app_dir / "server.log"
        with open(log_path, "a") as logf:
            subprocess.Popen(
                [sys.executable, "-m", "router.main"],
                stdout=logf,
                stderr=logf,
                start_new_session=True,
            )

        # Wait for the server to accept connections (up to 20s)
        for _ in range(20):
            time.sleep(1)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex(("127.0.0.1", MULLM_PORT)) == 0:
                    self._log(f"  Server is ready on port {MULLM_PORT}")
                    return

        raise RuntimeError(
            f"muLLM server did not start within 20 seconds.\n"
            f"Check the log at: {log_path}"
        )

    # ── Headless fallback ─────────────────────────────────────────────────────

    def _run_headless(self):
        """No GUI available — run bootstrap and print to stdout."""
        steps = [
            ("Checking Python…",               self._check_python),
            ("Installing muLLM…",              self._install_mullm),
            ("Detecting GPU / metal backend…", self._detect_gpu),
            ("Checking Ollama…",               self._check_ollama),
            ("Starting server…",               self._start_server),
        ]
        for label, fn in steps:
            print(f"[muLLM] {label}")
            fn()

        print(f"[muLLM] Ready! Opening {SETUP_URL}")
        webbrowser.open(SETUP_URL)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    BootstrapUI()
