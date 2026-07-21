"""scrubber/phone_providers.py — pluggable people-search sources.

`tps_match.select_record()` is already provider-agnostic: it consumes
`PersonRecord`s and decides which one is the merchant. This module is the other
half — where those records come from — so adding a real skip-trace vendor is a
new class here plus a credential, and touches nothing else.

STATE OF PLAY (2026-07-21). No provider can run on this box:
  - TruePeopleSearch answers this VPS with an HTTP 403 captcha interstitial
    (`scripts/tps_probe.py --reachability`). It is registered below because the
    fetch code exists and the block may not apply from other egress, but it is
    NOT enabled by default.
  - CLEAR is credentialed and its adapter is deliberately NOT written yet:
    without the credentials and API docs, its request/response contract would be
    invented and untestable.
  - No skip-trace API key of any kind is present in .env.agents.

So `resolve_provider()` returns None with a logged reason, and the enricher
routes those deals to manual review — which is the intended product behaviour,
not a degraded mode. When a credential arrives, implement `search()` and add one
registry entry.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

from scrubber import tps_match

#: Per-lookup guardrails shared by every provider. Paid vendors bill per
#: lookup, so an ambiguous merchant must never burn an unbounded number.
DEFAULT_MIN_INTERVAL_S = 2.0
DEFAULT_MAX_CALLS = 8


@runtime_checkable
class PhoneProvider(Protocol):
    """A source of people records for a merchant."""

    name: str

    def available(self, env: dict[str, str]) -> tuple[bool, str]:
        """(usable?, human-readable reason). The reason is logged when unusable,
        so "why isn't the lookup running" is always an answerable question."""
        ...

    def search(self, merchant: dict[str, Any], env: dict[str, str]) -> list[tps_match.PersonRecord]:
        """Records for this merchant. Return [] rather than raising on a miss;
        raise only on a genuine transport/credential fault."""
        ...


class TruePeopleSearchProvider:
    """The existing scrape path, kept as a reference implementation.

    Disabled unless TPS_PROVIDER_ENABLED=1, because from this host it returns a
    captcha page rather than results. Enabling it does not bypass anything — it
    just lets the fetch run where the block may not apply."""

    name = "truepeoplesearch"

    def available(self, env: dict[str, str]) -> tuple[bool, str]:
        if str(env.get("TPS_PROVIDER_ENABLED") or "0").strip() != "1":
            return False, "disabled (TPS_PROVIDER_ENABLED != 1); this host gets an HTTP 403 captcha page"
        from _bravo_bootstrap import resolve_bravo_root

        root = resolve_bravo_root()
        if not root or not (Path(root) / "scripts" / "research_fetch.py").is_file():
            return False, "research_fetch.py not found"
        return True, "enabled"

    def search(self, merchant: dict[str, Any], env: dict[str, str]) -> list[tps_match.PersonRecord]:
        import uw_lead_enricher as E  # local import: avoids a circular import at module load

        text = E._fetch_truepeople_text(merchant)
        return tps_match.parse_records(text or "")


#: Ordered by preference. A credentialed vendor belongs ABOVE the scrape path.
_REGISTRY: list[PhoneProvider] = [TruePeopleSearchProvider()]


def resolve_provider(
    env: Optional[dict[str, str]] = None,
    log: Any = None,
) -> Optional[PhoneProvider]:
    """The first usable provider, or None with every rejection logged."""
    env = env if env is not None else dict(os.environ)
    emit = log or (lambda m: print(f"[phone-providers] {m}", file=sys.stderr))
    for p in _REGISTRY:
        ok, why = p.available(env)
        if ok:
            emit(f"provider: {p.name} ({why})")
            return p
        emit(f"provider {p.name} unavailable: {why}")
    emit("no phone provider available — deals route to manual review")
    return None


def new_rate_limiter(env: Optional[dict[str, str]] = None) -> tps_match.RateLimiter:
    env = env if env is not None else dict(os.environ)

    def _num(key: str, default: float) -> float:
        try:
            return float(str(env.get(key) or default))
        except (TypeError, ValueError):
            return default

    return tps_match.RateLimiter(
        min_interval_s=_num("PHONE_LOOKUP_MIN_INTERVAL_S", DEFAULT_MIN_INTERVAL_S),
        max_calls=int(_num("PHONE_LOOKUP_MAX_CALLS", DEFAULT_MAX_CALLS)),
    )
