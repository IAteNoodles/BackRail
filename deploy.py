#!/usr/bin/env python3
"""
Deploy script for BackRail — RDSO Document Management Backend.

Usage:
    python deploy.py                  # Full setup + run
    python deploy.py --setup          # Setup only (venv, deps, migrate, static)
    python deploy.py --run            # Run production server only
    python deploy.py --populate       # Populate mock data
    python deploy.py --host 0.0.0.0   # Bind to specific host
    python deploy.py --port 8000      # Bind to specific port
    python deploy.py --dev            # Run in development mode (DEBUG=True)
"""

import argparse
import os
import platform
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR / "backend" / "app"
REQUIREMENTS = SCRIPT_DIR / "requirements.txt"
VENV_DIR = SCRIPT_DIR / "stable-env"
ENV_FILE = BACKEND_DIR / ".env"

IS_WINDOWS = platform.system() == "Windows"
PYTHON_BIN = VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") / ("python.exe" if IS_WINDOWS else "python")
PIP_BIN = VENV_DIR / ("Scripts" if IS_WINDOWS else "bin") / ("pip.exe" if IS_WINDOWS else "pip")


def log(msg: str, level: str = "INFO"):
    colours = {"INFO": "\033[94m", "OK": "\033[92m", "WARN": "\033[93m", "ERR": "\033[91m"}
    reset = "\033[0m"
    prefix = colours.get(level, "")
    print(f"{prefix}[{level}]{reset} {msg}")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True):
    """Run a subprocess command."""
    log(f"  $ {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, cwd=cwd, capture_output=False)
    if check and result.returncode != 0:
        log(f"Command failed with exit code {result.returncode}", "ERR")
        sys.exit(1)
    return result


def check_git_pull():
    """Check if git pull is available and prompt the user."""
    try:
        log("Checking for updates from remote repository...")
        subprocess.run(["git", "fetch"], check=True, capture_output=True)
        status_result = subprocess.run(["git", "status", "-uno"], capture_output=True, text=True)
        if "Your branch is behind" in status_result.stdout:
            log("A newer version is available on the remote repository.", "WARN")
            ans = input("\033[93mDo you want to run 'git pull' now? [Y/n]: \033[0m").strip().lower()
            if ans in ('', 'y', 'yes'):
                log("Pulling latest changes...")
                run(["git", "pull"])
                log("Pull complete.", "OK")
            else:
                log("Skipping git pull.")
        else:
            log("Repository is up to date.", "OK")
    except Exception as e:
        log(f"Failed to check git status: {e}", "WARN")


def kill_port(port: int):
    """Find and kill any process listening on the specified port."""
    log(f"Checking if port {port} is in use...")
    try:
        if IS_WINDOWS:
            result = subprocess.run(f"netstat -ano | findstr :{port}", shell=True, capture_output=True, text=True)
            if result.stdout:
                for line in result.stdout.strip().split('\n'):
                    parts = line.strip().split()
                    if len(parts) >= 5 and parts[3] == "LISTENING":
                        pid = parts[4]
                        log(f"Port {port} is used by PID {pid}. Killing it...", "WARN")
                        subprocess.run(f"taskkill /PID {pid} /F", shell=True, capture_output=True)
        else:
            result = subprocess.run(["lsof", "-t", f"-i:{port}"], capture_output=True, text=True)
            if result.stdout:
                for pid in result.stdout.strip().split():
                    log(f"Port {port} is used by PID {pid}. Killing it...", "WARN")
                    subprocess.run(["kill", "-9", pid], capture_output=True)
    except Exception as e:
        log(f"Error while trying to free port {port}: {e}", "WARN")


def create_venv():
    """Create virtual environment if it doesn't exist."""
    if VENV_DIR.exists() and PYTHON_BIN.exists():
        log("Virtual environment already exists", "OK")
        return
    log("Creating virtual environment...")
    run([sys.executable, "-m", "venv", str(VENV_DIR)])
    log("Virtual environment created", "OK")


def install_deps():
    """Install Python dependencies from requirements.txt."""
    if not REQUIREMENTS.exists():
        log("requirements.txt not found!", "ERR")
        sys.exit(1)
    log("Installing dependencies...")
    run([str(PIP_BIN), "install", "--upgrade", "pip"])
    run([str(PIP_BIN), "install", "-r", str(REQUIREMENTS)])
    # Install gunicorn for production (Unix only)
    if not IS_WINDOWS:
        run([str(PIP_BIN), "install", "gunicorn"])
    else:
        run([str(PIP_BIN), "install", "waitress"])
    log("Dependencies installed", "OK")


def ensure_env(dev: bool = False):
    """Create .env file with secure defaults if it doesn't exist."""
    if ENV_FILE.exists():
        log(".env file already exists", "OK")
        return
    log("Creating .env file with secure defaults...")
    secret_key = secrets.token_urlsafe(50)
    env_content = (
        f'DJANGO_SECRET_KEY="{secret_key}"\n'
        f'DEBUG={"True" if dev else "False"}\n'
    )
    ENV_FILE.write_text(env_content, encoding="utf-8")
    log(f".env created at {ENV_FILE}", "OK")


def run_manage(args: list[str]):
    """Run a Django manage.py command."""
    run([str(PYTHON_BIN), "manage.py"] + args, cwd=BACKEND_DIR)


def migrate():
    """Run database migrations."""
    log("Running migrations...")
    run_manage(["migrate", "--noinput"])
    log("Migrations complete", "OK")


def collect_static():
    """Collect static files for production."""
    log("Collecting static files...")
    run_manage(["collectstatic", "--noinput", "--clear"])
    log("Static files collected", "OK")


def populate():
    """Populate database with mock data."""
    log("Populating mock data...")
    run_manage(["populate_mock_data"])
    log("Mock data populated", "OK")


def setup(dev: bool = False):
    """Full setup: venv, deps, env, migrate, static."""
    log("=" * 60)
    log("  BackRail Backend — Setup")
    log("=" * 60)
    create_venv()
    install_deps()
    ensure_env(dev)
    migrate()
    if not dev:
        collect_static()
    log("=" * 60)
    log("  Setup complete!", "OK")
    log("=" * 60)


def run_server(host: str = "0.0.0.0", port: int = 8000, dev: bool = False):
    """Start the server."""
    if dev:
        log(f"Starting Django dev server on {host}:{port}...")
        run_manage(["runserver", f"{host}:{port}"])
    else:
        log(f"Starting production server on {host}:{port}...")
        if IS_WINDOWS:
            # Use waitress on Windows
            run(
                [str(PYTHON_BIN), "-c",
                 f"from waitress import serve; "
                 f"import django; import os; "
                 f"os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings'); "
                 f"django.setup(); "
                 f"from app.wsgi import application; "
                 f"print('Serving on http://{host}:{port}'); "
                 f"serve(application, host='{host}', port={port})"],
                cwd=BACKEND_DIR,
            )
        else:
            # Use gunicorn on Linux/macOS
            gunicorn_bin = VENV_DIR / "bin" / "gunicorn"
            run(
                [str(gunicorn_bin), "app.wsgi:application",
                 "--bind", f"{host}:{port}",
                 "--workers", "4",
                 "--timeout", "120",
                 "--access-logfile", "-"],
                cwd=BACKEND_DIR,
            )


def main():
    parser = argparse.ArgumentParser(
        description="Deploy BackRail backend server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--setup", action="store_true", help="Run setup only (venv, deps, migrate, static)")
    parser.add_argument("--run", action="store_true", help="Run server only (skip setup)")
    parser.add_argument("--populate", action="store_true", help="Populate mock data and exit")
    parser.add_argument("--dev", action="store_true", help="Development mode (DEBUG=True, Django runserver)")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")

    args = parser.parse_args()

    os.chdir(SCRIPT_DIR)
    
    # Optional update check before starting
    check_git_pull()

    if args.populate:
        populate()
        return

    if args.setup:
        setup(dev=args.dev)
        return

    if args.run:
        kill_port(args.port)
        run_server(host=args.host, port=args.port, dev=args.dev)
        return

    # Default: full setup + run
    setup(dev=args.dev)
    kill_port(args.port)
    run_server(host=args.host, port=args.port, dev=args.dev)


if __name__ == "__main__":
    main()
