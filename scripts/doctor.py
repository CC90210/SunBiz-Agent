"""
Sun Biz Agent runtime doctor.

Checks the repo-local production surface Ezra would rely on:
- environment file + required keys
- core dependencies
- SMS engine readiness
- JotForm and Gmail configuration
- hosted API security configuration

Usage:
    python scripts/doctor.py
    python scripts/doctor.py --json
    python scripts/doctor.py --deep --json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import smtplib
import ssl
import sys
from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env.agents"
ENV_TEMPLATE_PATH = PROJECT_ROOT / ".env.agents.template"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

FRIENDLY_CHECK_NAMES = {
    "python_version": "Solara runtime",
    "env_template": "Credentials template",
    "env_file": "Credentials file",
    "repo_surface": "Runtime files",
    "sms_phase1_env": "Text Torrent credentials",
    "gmail_env": "Email credentials",
    "jotform_env": "JotForm credentials",
    "api_security_env": "Hosted API signing secret",
    "sms_phase2_failover_env": "Phase 2 SMS failover",
    "leadgen_env": "Optional lead-gen keys",
    "sms_engine": "SMS transport",
    "gmail_live": "Live Gmail connection",
    "jotform_live": "Live JotForm connection",
}


@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str
    required: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def resolve_env(key: str, env: dict[str, str]) -> str:
    return os.environ.get(key) or env.get(key, "")


def module_installed(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None


def key_is_configured(value: str) -> bool:
    if not value:
        return False
    upper = value.upper()
    return "INSERT_" not in upper and value not in {"changeme", "replace-me"}


def check_key_group(
    name: str,
    keys: Iterable[str],
    env: dict[str, str],
    *,
    required: bool,
    missing_message: str | None = None,
) -> Check:
    missing = [key for key in keys if not key_is_configured(resolve_env(key, env))]
    if not missing:
        return Check(name=name, status="ok", detail="configured", required=required)
    status = "fail" if required else "warn"
    detail = missing_message or ("missing: " + ", ".join(missing))
    return Check(name=name, status=status, detail=detail, required=required)


def run_gmail_login(env: dict[str, str]) -> Check:
    # GMAIL_USER is the canonical key (written by provision_secrets + read by
    # send_gateway/email_blast); fall back to GMAIL_ADDRESS for back-compat.
    address = resolve_env("GMAIL_USER", env) or resolve_env("GMAIL_ADDRESS", env)
    password = resolve_env("GMAIL_APP_PASSWORD", env)
    if not (key_is_configured(address) and key_is_configured(password)):
        return Check(
            name="gmail_live",
            status="fail",
            detail="Gmail credentials are not fully configured",
            required=True,
        )
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(address, password)
        return Check(name="gmail_live", status="ok", detail="SMTP login succeeded", required=True)
    except Exception as exc:  # noqa: BLE001
        return Check(
            name="gmail_live",
            status="fail",
            detail=f"SMTP login failed: {str(exc)[:200]}",
            required=True,
        )


def run_jotform_probe(env: dict[str, str]) -> Check:
    api_key = resolve_env("JOTFORM_API_KEY", env)
    form_id = resolve_env("JOTFORM_FORM_ID", env)
    if not (key_is_configured(api_key) and key_is_configured(form_id)):
        return Check(
            name="jotform_live",
            status="fail",
            detail="JotForm credentials are not fully configured",
            required=True,
        )
    try:
        from jotform_tracker import JotFormTracker

        tracker = JotFormTracker()
        info = tracker.get_form_info()
        title = info.get("title", "(unknown form)")
        return Check(
            name="jotform_live",
            status="ok",
            detail=f"connected to form '{title}'",
            required=True,
        )
    except SystemExit as exc:
        return Check(
            name="jotform_live",
            status="fail",
            detail=f"tracker exited early: {exc}",
            required=True,
        )
    except Exception as exc:  # noqa: BLE001
        return Check(
            name="jotform_live",
            status="fail",
            detail=f"JotForm probe failed: {str(exc)[:200]}",
            required=True,
        )


def build_report(*, include_live_checks: bool = False) -> dict:
    env = load_env_file(ENV_PATH)
    checks: list[Check] = []

    checks.append(
        Check(
            name="python_version",
            status="ok" if sys.version_info >= (3, 10) else "fail",
            detail=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            required=True,
        )
    )
    checks.append(
        Check(
            name="env_template",
            status="ok" if ENV_TEMPLATE_PATH.exists() else "fail",
            detail=str(ENV_TEMPLATE_PATH),
            required=True,
        )
    )
    checks.append(
        Check(
            name="env_file",
            status="ok" if ENV_PATH.exists() else "fail",
            detail=str(ENV_PATH) if ENV_PATH.exists() else ".env.agents missing",
            required=True,
        )
    )

    required_paths = [
        PROJECT_ROOT / "templates" / "email",
        PROJECT_ROOT / "dashboard" / "tenant.manifest.json",
        PROJECT_ROOT / "scripts" / "sms_engine.py",
        PROJECT_ROOT / "scripts" / "email_blast.py",
        PROJECT_ROOT / "scripts" / "jotform_tracker.py",
        PROJECT_ROOT / "scripts" / "api_server.py",
    ]
    missing_paths = [str(path.relative_to(PROJECT_ROOT)) for path in required_paths if not path.exists()]
    checks.append(
        Check(
            name="repo_surface",
            status="ok" if not missing_paths else "fail",
            detail="all required runtime files present" if not missing_paths else "missing: " + ", ".join(missing_paths),
            required=True,
        )
    )

    module_checks = {
        "python-dotenv": ("dotenv", True),
        "requests": ("requests", True),
        "jinja2": ("jinja2", True),
        "twilio": ("twilio", True),
        "fastapi": ("fastapi", True),
        "uvicorn": ("uvicorn", True),
        "facebook-business": ("facebook_business", False),
        "google-ads": ("google.ads", False),
        "google-genai": ("google.genai", False),
    }
    for label, (module_name, required) in module_checks.items():
        checks.append(
            Check(
                name=f"dependency:{label}",
                status="ok" if module_installed(module_name) else ("fail" if required else "warn"),
                detail="installed" if module_installed(module_name) else "not installed",
                required=required,
            )
        )

    checks.append(
        check_key_group(
            "sms_phase1_env",
            (
                "SUNBIZ_TWILIO_ACCOUNT_SID",
                "SUNBIZ_TWILIO_AUTH_TOKEN",
                "SUNBIZ_TWILIO_FROM_NUMBER",
            ),
            env,
            required=True,
        )
    )
    checks.append(
        check_key_group(
            "gmail_env",
            (
                "GMAIL_ADDRESS",
                "GMAIL_APP_PASSWORD",
                "EMAIL_FROM_NAME",
                "EMAIL_UNSUBSCRIBE_BASE_URL",
            ),
            env,
            required=True,
        )
    )
    checks.append(
        check_key_group(
            "jotform_env",
            ("JOTFORM_API_KEY", "JOTFORM_FORM_ID"),
            env,
            required=True,
        )
    )
    checks.append(
        check_key_group(
            "api_security_env",
            ("SUNBIZ_AGENT_HMAC_SECRET",),
            env,
            required=True,
            missing_message="missing: SUNBIZ_AGENT_HMAC_SECRET (required for dashboard-signed hosted requests)",
        )
    )
    checks.append(
        check_key_group(
            "sms_phase2_failover_env",
            (
                "SUNBIZ_TELNYX_API_KEY",
                "SUNBIZ_TELNYX_FROM_NUMBER",
                "SUNBIZ_PLIVO_AUTH_ID",
                "SUNBIZ_PLIVO_AUTH_TOKEN",
                "SUNBIZ_PLIVO_FROM_NUMBER",
            ),
            env,
            required=False,
            missing_message="phase-2 failover providers not configured yet",
        )
    )
    checks.append(
        check_key_group(
            "leadgen_env",
            (
                "GOOGLE_ADS_DEVELOPER_TOKEN",
                "META_ACCESS_TOKEN",
                "GEMINI_API_KEY",
            ),
            env,
            required=False,
            missing_message="lead-gen sub-capability keys are still optional / partial",
        )
    )

    try:
        from sms_engine import status as sms_status

        sms = sms_status()
        configured = ", ".join(sms.get("providers_configured", [])) or "(none)"
        sdk_installed = bool(sms.get("twilio_sdk_installed"))
        sms_ok = "twilio" in sms.get("providers_configured", []) and sdk_installed
        checks.append(
            Check(
                name="sms_engine",
                status="ok" if sms_ok else "fail",
                detail=f"providers={configured}; twilio_sdk_installed={sdk_installed}",
                required=True,
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(
            Check(
                name="sms_engine",
                status="fail",
                detail=f"sms_engine import failed: {str(exc)[:200]}",
                required=True,
            )
        )

    if include_live_checks:
        checks.append(run_gmail_login(env))
        checks.append(run_jotform_probe(env))

    required_failures = [check for check in checks if check.required and check.status == "fail"]
    warnings = [check for check in checks if check.status == "warn"]
    if required_failures:
        verdict = "UNHEALTHY"
    elif warnings:
        verdict = "DEGRADED"
    else:
        verdict = "HEALTHY"

    return {
        "verdict": verdict,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo_root": str(PROJECT_ROOT),
        "deep_checks": include_live_checks,
        "checks": [check.to_dict() for check in checks],
        "summary": {
            "ok": sum(1 for check in checks if check.status == "ok"),
            "warn": sum(1 for check in checks if check.status == "warn"),
            "fail": sum(1 for check in checks if check.status == "fail"),
        },
    }


def print_human(report: dict) -> None:
    print("=" * 64)
    print("SOLARA PULSE CHECK")
    print("=" * 64)
    print(f"Verdict    : {report['verdict']}")
    print(f"Checked at : {report['checked_at']}")
    print(f"Deep check : {report['deep_checks']}")
    print("")
    for check in report["checks"]:
        marker = {
            "ok": "[OK]  ",
            "warn": "[WARN]",
            "fail": "[FAIL]",
        }[check["status"]]
        scope = "required" if check["required"] else "optional"
        label = FRIENDLY_CHECK_NAMES.get(check["name"], check["name"])
        print(f"{marker} {label} ({scope})")
        print(f"       {check['detail']}")
    print("")
    summary = report["summary"]
    print(f"Summary    : ok={summary['ok']} warn={summary['warn']} fail={summary['fail']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sun Biz Agent production doctor")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--deep", action="store_true", help="Run live JotForm and Gmail connectivity checks")
    args = parser.parse_args(argv)

    report = build_report(include_live_checks=args.deep)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)

    verdict = report["verdict"]
    if verdict == "HEALTHY":
        return 0
    if verdict == "DEGRADED":
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
