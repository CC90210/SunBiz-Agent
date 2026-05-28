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
