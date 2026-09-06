#!/usr/bin/env python3
"""
Crime Analysis — one-command launcher.

Automatically:
  1. Creates a Python virtual environment (if needed)
  2. Installs backend dependencies (FastAPI, SQLAlchemy, JWT, pypdf, ...)
  3. Installs frontend dependencies (npm) and builds the React app
  4. Starts the FastAPI server (serves both the /api backend and the React UI)
  5. Opens the application in your default browser

Usage:
    python run.py                     # install + build + run + open browser
    python run.py --no-browser        # skip opening the browser
    python run.py --port 8001         # run on a different port
    python run.py --host 0.0.0.0      # bind to all interfaces
    python run.py --skip-install      # skip dependency installation
    python run.py --skip-build        # skip the frontend build
    python run.py --reinstall         # force a fresh dependency install

Demo credentials:
    investigator1 / investor1
    investigator2 / investor2
    admin         / admin123
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
REQUIREMENTS = BACKEND / "requirements.txt"
DIST = FRONTEND / "dist"

IS_WINDOWS = os.name == "nt"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def venv_python():
    return VENV / ("Scripts" if IS_WINDOWS else "bin") / ("python.exe" if IS_WINDOWS else "python")


def venv_bin(name):
    return VENV / ("Scripts" if IS_WINDOWS else "bin") / (name + (".exe" if IS_WINDOWS else ""))


def npm_cmd():
    return "npm.cmd" if IS_WINDOWS else "npm"


def run(cmd, cwd=None, env=None, check=True):
    """Run a command, streaming output, and return the completed process."""
    print("  $ " + " ".join(str(c) for c in cmd))
    return subprocess.run(cmd, cwd=cwd, env=env, check=check)


def step(msg):
    print(f"\n==> {msg}")


def banner():
    print("=" * 62)
    print("  Crime Analysis — AI-Powered Criminal Network Analysis")
    print("=" * 62)


# --------------------------------------------------------------------------- #
# steps
# --------------------------------------------------------------------------- #
def ensure_venv():
    if venv_python().exists():
        return
    step("Creating Python virtual environment (.venv)")
    run([sys.executable, "-m", "venv", str(VENV)])


def install_backend(reinstall):
    if not REQUIREMENTS.exists():
        print("  ! backend/requirements.txt not found — skipping backend install")
        return
    marker = VENV / ".crime_analysis_backend_installed"
    if not reinstall and marker.exists():
        return
    step("Installing backend dependencies (pip)")
    run([str(venv_python()), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(venv_python()), "-m", "pip", "install", "-r", str(REQUIREMENTS)])
    marker.write_text("ok")


def install_frontend(reinstall, skip_build):
    if not (FRONTEND / "package.json").exists():
        print("  ! frontend/package.json not found — skipping frontend")
        return
    node_modules = FRONTEND / "node_modules"
    if reinstall or not node_modules.exists():
        step("Installing frontend dependencies (npm)")
        run([npm_cmd(), "install", "--no-audit", "--no-fund"], cwd=FRONTEND)
    if skip_build:
        return
    if DIST.exists() and not reinstall:
        # quick freshness check: rebuild only when source is newer than dist
        src_newer = _any_newer(FRONTEND / "src", DIST)
        if not src_newer and not _any_newer(FRONTEND / "index.html", DIST):
            return
    step("Building frontend (npm run build)")
    run([npm_cmd(), "run", "build"], cwd=FRONTEND)


def _any_newer(src, dist):
    if not src.exists():
        return False
    dist_time = dist.stat().st_mtime
    if src.is_dir():
        for p in src.rglob("*"):
            if p.is_file() and p.stat().st_mtime > dist_time:
                return True
        return False
    return src.stat().st_mtime > dist_time


def wait_for_server(url, timeout=90):
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(0.5)
    print(f"  ! server did not respond at {url}: {last_err}")
    return False


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(description="Run Crime Analysis end-to-end")
    parser.add_argument("--host", default=os.getenv("CRIME_ANALYSIS_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("CRIME_ANALYSIS_PORT", "8000")))
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    parser.add_argument("--skip-install", action="store_true", help="skip dependency installs")
    parser.add_argument("--skip-build", action="store_true", help="skip the frontend build")
    parser.add_argument("--reinstall", action="store_true", help="force fresh dependency install")
    args = parser.parse_args()

    banner()

    if shutil.which("python3") is None and shutil.which("python") is None:
        print("Python is required to run Crime Analysis.")
        sys.exit(1)
    if shutil.which(npm_cmd()) is None:
        print("Node.js / npm is required to build the Crime Analysis frontend.")
        print("Install Node.js from https://nodejs.org and retry.")
        sys.exit(1)

    # 1. virtualenv
    ensure_venv()

    # 2. dependencies
    if not args.skip_install:
        install_backend(args.reinstall)
        install_frontend(args.reinstall, args.skip_build)
    else:
        print("\n==> Skipping dependency installation (--skip-install)")

    # 3. start server
    base_url = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    step(f"Starting Crime Analysis server at {base_url}")
    uvicorn = str(venv_bin("uvicorn"))
    server = subprocess.Popen(
        [uvicorn, "app.main:app", "--host", args.host, "--port", str(args.port)],
        cwd=BACKEND,
    )

    try:
        # 4. wait until ready
        step("Waiting for the server to be ready…")
        if wait_for_server(f"{base_url}/health"):
            print("\n  ✓ Crime Analysis is running!")
            print(f"  ✓ Open {base_url} in your browser")
            print("\n  Demo logins:")
            print("      investigator1 / investor1")
            print("      investigator2 / investor2")
            print("      admin         / admin123")
            if not args.no_browser:
                time.sleep(1)
                print("\n==> Opening browser…")
                webbrowser.open(base_url)
        else:
            print("\n  ! Server failed to start. See logs above.")
            server.terminate()
            sys.exit(1)

        # 5. keep alive until Ctrl+C
        print("\n  (Press Ctrl+C to stop)\n")
        server.wait()
    except KeyboardInterrupt:
        print("\n\n==> Shutting down Crime Analysis…")
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        print("  ✓ Stopped.")


if __name__ == "__main__":
    main()
