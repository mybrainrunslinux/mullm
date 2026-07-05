#!/usr/bin/env python3
"""
muLLM Windows Launcher — bootstraps the full stack with a native-looking GUI.

Packed with PyInstaller (--onefile --windowed --noconsole) so the user
double-clicks muLLM.exe and sees a progress window, not a console.

Branding: amber #f59e0b on slate #0f172a  (matches the web UI)
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import webbrowser
import winreg
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

PYTHON_MIN = (3, 11)
PYTHON_DOWNLOAD_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"

# Branding colours
BG_DARK = "#0f172a"
BG_CARD = "#1e293b"
AMBER = "#f59e0b"
AMBER_DARK = "#d97706"
TEXT_WHITE = "#f8fafc"
TEXT_MUTED = "#94a3b8"

# Registry paths to locate Python on Windows
_PY_REG_PATHS = [
    r"SOFTWARE\Python\PythonCore",
    r"SOFTWARE\WOW6432Node\Python\PythonCore",
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _find_python_in_registry() -> str | None:
    """Return the path to the latest Python 3.11+ interpreter via the registry."""
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for reg_path in _PY_REG_PATHS:
            try:
                with winreg.OpenKey(hive, reg_path) as key:
                    i = 0
                    while True:
                        try:
                            ver_str = winreg.EnumKey(key, i)
                            i += 1
                            try:
                                major, minor = (int(x) for x in ver_str.split(".")[:2])
                            except ValueError:
                                continue
                            if (major, minor) < PYTHON_MIN:
                                continue
                            install_path_key = rf"{reg_path}\{ver_str}\InstallPath"
                            with winreg.OpenKey(hive, install_path_key) as ip:
                                install_dir, _ = winreg.QueryValueEx(ip, "ExecutablePath")
                                if install_dir and Path(install_dir).exists():
                                    return install_dir
                        except OSError:
                            break
            except OSError:
                continue
    return None


def _detect_nvidia_cuda() -> str | None:
    """Return the CUDA version string if an NVIDIA GPU is present, else None."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


# ── GUI launcher ───────────────────────────────────────────────────────────────
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
        t = threading.Thread(target=self._run_steps, daemon=True)
        t.start()
        self.root.mainloop()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        header = tk.Frame(self.root, bg=AMBER, height=4)
        header.pack(fill="x", side="top")

        title_frame = tk.Frame(self.root, bg=BG_DARK, pady=18)
        title_frame.pack(fill="x")

        tk.Label(
            title_frame,
            text="μ|LLM",
            font=("Segoe UI", 28, "bold"),
            fg=AMBER,
            bg=BG_DARK,
        ).pack()

        tk.Label(
            title_frame,
            text="Local-first AI router",
            font=("Segoe UI", 11),
            fg=TEXT_MUTED,
            bg=BG_DARK,
        ).pack()

        self.status_var = tk.StringVar(value="Starting up…")
        self.status_label = tk.Label(
            self.root,
            textvariable=self.status_var,
            font=("Segoe UI", 11),
            fg=TEXT_WHITE,
            bg=BG_DARK,
            wraplength=460,
        )
        self.status_label.pack(pady=(0, 8))

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

        log_frame = tk.Frame(self.root, bg=BG_CARD, padx=8, pady=6)
        log_frame.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        self.log_text = tk.Text(
            log_frame,
            height=6,
            font=("Consolas", 9),
            fg=TEXT_MUTED,
            bg=BG_CARD,
            insertbackground=AMBER,
            relief="flat",
            wrap="word",
            state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)

    def _log(self, msg: str):
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
        def _update():
            self.status_var.set(msg)
            self.progress["value"] = pct

        if HAS_TK and hasattr(self, "root"):
            try:
                self.root.after(0, _update)
            except Exception:
                pass

    def _finish_success(self):
        def _close():
            webbrowser.open(SETUP_URL)
            self.root.destroy()

        if HAS_TK and hasattr(self, "root"):
            self.root.after(1500, _close)

    def _finish_error(self, msg: str):
        def _show():
            messagebox.showerror("muLLM Setup Failed", msg)
            self.root.destroy()
            sys.exit(1)

        if HAS_TK and hasattr(self, "root"):
            self.root.after(0, _show)

    # ── Bootstrap steps ───────────────────────────────────────────────────────

    def _run_steps(self):
        steps = [
            (10, "Checking Python…",             self._check_python),
            (30, "Installing muLLM…",            self._install_mullm),
            (55, "Detecting GPU / CUDA…",         self._detect_gpu),
            (75, "Checking Ollama…",             self._check_ollama),
            (90, "Starting muLLM server…",        self._start_server),
            (100, "Ready! Opening browser…",      lambda: None),
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

        self._log(f"muLLM is running on port {MULLM_PORT}. Opening your browser…")
        self._finish_success()

    def _check_python(self):
        v = sys.version_info
        self._log(f"  Python {v.major}.{v.minor}.{v.micro}")

        if v >= PYTHON_MIN:
            return  # current interpreter is fine

        # Try to find a better Python in the registry
        reg_py = _find_python_in_registry()
        if reg_py:
            self._log(f"  Found Python 3.11+ at {reg_py} — restarting with it")
            os.execv(reg_py, [reg_py] + sys.argv)  # replace current process

        # No good Python found — prompt user
        msg = (
            f"muLLM requires Python 3.11 or later.\n"
            f"You have Python {v.major}.{v.minor}.\n\n"
            f"Download Python 3.11 from:\n{PYTHON_DOWNLOAD_URL}\n\n"
            "After installing, run muLLM.exe again."
        )
        if HAS_TK:
            open_it = messagebox.askyesno(
                "Python 3.11 Required",
                msg + "\n\nOpen the download page now?",
            )
            if open_it:
                webbrowser.open(PYTHON_DOWNLOAD_URL)
        else:
            print(f"[muLLM] {msg}")

        raise RuntimeError(f"Python 3.11+ required (found {v.major}.{v.minor})")

    def _install_mullm(self):
        try:
            import importlib.metadata
            installed = importlib.metadata.version("mullm")
            self._log(f"  mullm {installed} already installed")
            if installed == MULLM_VERSION:
                return
            self._log(f"  Upgrading to {MULLM_VERSION}…")
        except Exception:
            self._log("  mullm not found — installing…")

        # Prefer bundled wheel (placed alongside the .exe by the installer)
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
        """Install CUDA-enabled PyTorch if an NVIDIA GPU is detected."""
        cuda = _detect_nvidia_cuda()
        if cuda:
            self._log(f"  NVIDIA GPU detected (driver {cuda})")
            try:
                import torch
                if torch.cuda.is_available():
                    self._log(f"  PyTorch CUDA already available: {torch.version.cuda}")
                    return
            except ImportError:
                pass

            self._log("  Installing PyTorch with CUDA 12.8 support…")
            subprocess.check_call(
                [
                    sys.executable, "-m", "pip", "install",
                    "torch==2.7.0", "torchvision", "torchaudio",
                    "--index-url", "https://download.pytorch.org/whl/cu128",
                    "--quiet",
                ],
                timeout=600,
            )
            self._log("  PyTorch CUDA installed")
        else:
            self._log("  No NVIDIA GPU detected — using CPU / llama.cpp backend")
            # llama.cpp CPU build is pulled in as part of the mullm optional deps
            try:
                import llama_cpp  # noqa: F401
                self._log("  llama-cpp-python already installed")
            except ImportError:
                self._log("  Installing llama-cpp-python (CPU build)…")
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install",
                     "llama-cpp-python", "--quiet"],
                    timeout=300,
                )

    def _check_ollama(self):
        """Check for Ollama; open download page if missing."""
        ollama_paths = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
            Path("C:/Program Files/Ollama/ollama.exe"),
        ]
        ollama_exe = None
        for p in ollama_paths:
            if p.exists():
                ollama_exe = str(p)
                break

        if not ollama_exe:
            try:
                result = subprocess.run(["ollama", "list"], capture_output=True, timeout=5)
                if result.returncode == 0:
                    ollama_exe = "ollama"
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass

        if ollama_exe:
            self._log(f"  Ollama found: {ollama_exe}")
            return

        self._log("  Ollama not found")
        if HAS_TK:
            open_it = messagebox.askyesno(
                "Install Ollama?",
                "Ollama is not installed.\n\n"
                "muLLM uses Ollama to run local AI models.\n\n"
                "Open the Ollama download page?\n"
                "(You can also skip this and use API keys instead.)",
            )
            if open_it:
                webbrowser.open("https://ollama.ai/download/windows")
                messagebox.showinfo(
                    "Install Ollama",
                    "After installing Ollama, click OK to continue.",
                )
        else:
            print("[muLLM] Ollama not found. Download from https://ollama.ai/download/windows")

    def _start_server(self):
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", MULLM_PORT)) == 0:
                self._log(f"  Server already running on port {MULLM_PORT}")
                return

        self._log(f"  Starting muLLM server on port {MULLM_PORT}…")

        app_dir = Path.home() / "AppData" / "Local" / "muLLM"
        app_dir.mkdir(parents=True, exist_ok=True)
        log_path = app_dir / "server.log"

        with open(log_path, "a") as logf:
            # DETACHED_PROCESS so the server survives closing the launcher
            DETACHED_PROCESS = 0x00000008
            CREATE_NO_WINDOW = 0x08000000
            subprocess.Popen(
                [sys.executable, "-m", "router.main"],
                stdout=logf,
                stderr=logf,
                creationflags=DETACHED_PROCESS | CREATE_NO_WINDOW,
            )

        for _ in range(20):
            time.sleep(1)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                if s.connect_ex(("127.0.0.1", MULLM_PORT)) == 0:
                    self._log(f"  Server ready on port {MULLM_PORT}")
                    return

        raise RuntimeError(
            f"muLLM server did not start within 20 seconds.\n"
            f"Check the log: {log_path}"
        )

    # ── Headless fallback ─────────────────────────────────────────────────────

    def _run_headless(self):
        steps = [
            ("Checking Python…",        self._check_python),
            ("Installing muLLM…",       self._install_mullm),
            ("Detecting GPU / CUDA…",    self._detect_gpu),
            ("Checking Ollama…",        self._check_ollama),
            ("Starting server…",        self._start_server),
        ]
        for label, fn in steps:
            print(f"[muLLM] {label}")
            fn()

        print(f"[muLLM] Ready! Opening {SETUP_URL}")
        webbrowser.open(SETUP_URL)


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    BootstrapUI()
