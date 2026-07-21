"""bravo_bootstrap.py — locate CEO-Agent runtime and bootstrap sys.path.

SunBiz daemons depend on shared infrastructure that lives in CEO-Agent:
  - lib.secret_loader (.env.agents reader)
  - integrations.send_gateway (universal outbound chokepoint)
  - integrations.google_tool (Gmail OAuth shim)
  - casl_compliance (DNC suppression)

This module is loaded BEFORE those cross-repo imports — that's why it
ships with SunBiz-Agent itself (importable as lib.bravo_bootstrap from
any daemon after sys.path includes SunBiz-Agent/scripts/) instead of
sitting on the CEO-Agent side.

Usage at the top of every SunBiz daemon:

    import sys
    from pathlib import Path
    REPO_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    from lib.bravo_bootstrap import bootstrap_bravo_path

    BRAVO_ROOT = bootstrap_bravo_path()  # adds CEO-Agent/scripts to sys.path
    # ... then standard cross-repo imports just work:
    from lib.secret_loader import load_env
    from integrations.send_gateway import send

resolve_bravo_root() returns the Path (or None) without touching
sys.path — for callers that need only the location, not the import
bootstrap.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def resolve_bravo_root() -> Path | None:
    """Locate the CEO-Agent runtime root. Honors BRAVO_AGENT_ROOT env
    var first, then probes the two canonical CC locations (~/CEO-Agent
    on Mac/Linux, C:\\Users\\User\\Business-Empire-Agent on Windows).
    Returns the resolved Path or None if no candidate has a scripts/
    subdir."""
    env = os.environ.get("BRAVO_AGENT_ROOT")
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env))
    candidates.append(Path.home() / "CEO-Agent")
    if os.name == "nt":
        candidates.append(Path("C:/Users/User/Business-Empire-Agent"))
    for c in candidates:
        if (c / "scripts").is_dir():
            return c
    return None


def bootstrap_bravo_path() -> Path | None:
    """Resolve CEO-Agent's root AND add its scripts/ to sys.path so
    cross-repo imports (lib.secret_loader, integrations.send_gateway,
    etc.) work without per-call sys.path edits. Returns the resolved
    Path (or None if not found). Idempotent — safe to call repeatedly."""
    bravo_root = resolve_bravo_root()
    if bravo_root is None:
        return None
    bravo_scripts = str(bravo_root / "scripts")
    if bravo_scripts not in sys.path:
        sys.path.insert(0, bravo_scripts)
    return bravo_root


#: Secrets that shared library code reads from os.environ rather than from the
#: env dict a daemon passes around. secret_loader deliberately does NOT touch
#: os.environ, so these must be mirrored across or those libraries silently
#: degrade — integrations.field_encryption falls back to "no key", which made
#: the scrubber store SSN last-4 only and would have made uw_lead_enricher strip
#: the encrypted SSN off any lead it refreshed from source.
_MIRROR_TO_ENVIRON = ("BRAVO_FIELD_ENCRYPTION_KEY",)


def _mirror_process_keys(env: dict[str, str]) -> dict[str, str]:
    for key in _MIRROR_TO_ENVIRON:
        value = env.get(key)
        if value and not os.environ.get(key):
            os.environ[key] = value
    return env


def load_bravo_env() -> dict[str, str]:
    """Read CEO-Agent's `.env.agents` via lib.secret_loader, WITHOUT depending on
    sys.path ordering. Falls back to os.environ if that's impossible.

    Why this exists (2026-07-21): SunBiz-Agent ships its own `scripts/lib/`
    package, and CEO-Agent ships `scripts/lib/secret_loader.py`. Whichever
    `scripts/` dir sits earlier on sys.path wins the name `lib` — and several
    daemons re-insert their OWN scripts/ at position 0 at import time (see
    mca_lead_scrubber). So a module that imports another daemon (uw_lead_enricher
    imports mca_lead_scrubber) silently flips `lib` back to SunBiz-Agent's after
    bootstrap ran, and `from lib.secret_loader import load_env` then raises
    ModuleNotFoundError.

    The daemons swallowed that and fell back to os.environ, which happened to
    carry the secrets from a historical `pm2 restart --update-env`. That made
    them work by accident and fail the moment they were restarted cleanly from
    ecosystem.config.js — which is exactly what happened to uw-lead-enricher.

    Loading the module from its resolved FILE PATH removes sys.path from the
    equation entirely, so it cannot be shadowed no matter what import order a
    caller produces.
    """
    bravo_root = resolve_bravo_root()
    if bravo_root is not None:
        path = bravo_root / "scripts" / "lib" / "secret_loader.py"
        if path.is_file():
            try:
                # Import under a private name so we never collide with, or get
                # served from, whatever `lib` currently resolves to.
                spec = importlib.util.spec_from_file_location("_bravo_secret_loader", path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    sys.modules.setdefault("_bravo_secret_loader", mod)
                    spec.loader.exec_module(mod)
                    return _mirror_process_keys(dict(mod.load_env()))
            except Exception as e:  # noqa: BLE001
                print(f"[bravo_bootstrap] secret_loader at {path} failed: {e}", file=sys.stderr)
    return dict(os.environ)
