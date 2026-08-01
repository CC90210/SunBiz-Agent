from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scrubber import push  # noqa: E402


def test_telegram_notifications_default_off(monkeypatch) -> None:
    monkeypatch.setattr(
        "scrubber.telegram_bridge.send_deal",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not send")),
    )

    push._notify_ezra({"EZRA_TELEGRAM_CHAT_ID": "123"}, [{"id": "candidate"}])


def test_telegram_notifications_require_explicit_opt_in(monkeypatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(
        "scrubber.telegram_bridge.send_deal",
        lambda _env, _row, candidate_id: sent.append(candidate_id) or {"ok": True},
    )

    push._notify_ezra(
        {
            "EZRA_TELEGRAM_CHAT_ID": "123",
            "EZRA_TELEGRAM_NOTIFICATIONS_ENABLED": "true",
        },
        [{"id": "candidate"}],
    )

    assert sent == ["candidate"]
