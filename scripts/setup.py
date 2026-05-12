"""
Sun Biz Agent setup script.

Installs repo dependencies, prepares local runtime directories, and runs the
repo-local doctor so the operator gets a clean "digital employee" onboarding
flow instead of raw infrastructure steps.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_PATH = PROJECT_ROOT / "requirements.txt"
ENV_PATH = PROJECT_ROOT / ".env.agents"
ENV_TEMPLATE_PATH = PROJECT_ROOT / ".env.agents.template"


def ensure_python_version() -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError(
            f"Python 3.10+ required, found {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        )


def install_requirements() -> None:
    if not REQUIREMENTS_PATH.exists():
        raise FileNotFoundError(f"requirements.txt missing at {REQUIREMENTS_PATH}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)])


def ensure_runtime_dirs() -> None:
    for relative in ("tmp", "data/email_logs", "data/email_lists"):
        (PROJECT_ROOT / relative).mkdir(parents=True, exist_ok=True)


def maybe_copy_env_template(copy_template: bool) -> bool:
    if ENV_PATH.exists():
        return False
    if not copy_template:
        return False
    if not ENV_TEMPLATE_PATH.exists():
        raise FileNotFoundError(f".env.agents.template missing at {ENV_TEMPLATE_PATH}")
    shutil.copyfile(ENV_TEMPLATE_PATH, ENV_PATH)
    return True


def run_doctor(json_output: bool) -> int:
    command = [sys.executable, str(PROJECT_ROOT / "scripts" / "doctor.py")]
    if json_output:
        command.append("--json")
    return subprocess.call(command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install and validate Sun Biz Agent")
    parser.add_argument(
        "--copy-env-template",
        action="store_true",
        help="Create .env.agents from .env.agents.template if it does not exist",
    )
    parser.add_argument(
        "--doctor-json",
        action="store_true",
        help="Run the post-install doctor in JSON mode",
    )
    args = parser.parse_args(argv)

    print("=" * 64)
    print("ONBOARDING YOUR NEW DIGITAL EMPLOYEE, SOLARA")
    print("=" * 64)

    ensure_python_version()
    print(f"[1/4] Solara's runtime is ready: Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")

    print("[2/4] Installing Solara's working tools...")
    install_requirements()

    print("[3/4] Preparing Solara's local workspace...")
    ensure_runtime_dirs()

    copied = maybe_copy_env_template(args.copy_env_template)
    if copied:
        print("[4/4] Created the credentials template. Add real JotForm, Text Torrent, and email credentials before production use.")
    else:
        print("[4/4] Existing credentials file left untouched.")

    print("")
    print("Running Solara pulse check...")
    doctor_exit = run_doctor(args.doctor_json)

    print("")
    print("Onboarding complete.")
    print("Next steps:")
    print("1. Add live JotForm, Text Torrent, and email credentials if any pulse checks failed.")
    print("2. Re-run `python scripts/doctor.py --deep` once those connections are wired.")
    print("3. Start the hosted runtime with `python scripts/api_server.py`.")

    return doctor_exit


if __name__ == "__main__":
    raise SystemExit(main())
