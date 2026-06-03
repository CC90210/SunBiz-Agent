#!/usr/bin/env python3
"""Regression test for the SunBiz sender-identity guard in scripts/email_blast.py.

Background: a SunBiz agent email once went out FROM the operator's personal
Gmail because the bridge ran on the operator's machine with their local
GMAIL_ADDRESS. The guard (_assert_sender_identity) must make that impossible:
SunBiz may only send as its own domain.

Dependency-free (no pytest): run with `python3 tests/test_email_identity_guard.py`.
Each scenario runs in a fresh subprocess because email_blast resolves the
sender at import time (same as its SMTP login).
"""
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO, "scripts")

SNIPPET = (
    "import sys; sys.path.insert(0, r'%s');\n"
    "import email_blast as e\n"
    "try:\n"
    "    ok = e.send_single_email('lead@acme.com','Hi','<p>hi</p>', dry_run=True, cc_email=%r)\n"
    "    print('SENT' if ok else 'FALSE')\n"
    "except RuntimeError:\n"
    "    print('REFUSED')\n"
) % (SCRIPTS, None)


def run(env_overrides):
    env = dict(os.environ)
    # Hermeticity: email_blast calls load_dotenv(.env.agents) at import with
    # override=False, which BACKFILLS any sender key we merely delete from the
    # env — so on a provisioned host (real GMAIL_USER=submissions@sunbizfunding.com)
    # the "negative" scenarios would resolve to a valid sender and wrongly SEND.
    # Neutralize the sender keys by setting them to "" (a present-but-empty env
    # var is NOT overridden by load_dotenv), so the file can't reintroduce an
    # identity. Each case's overrides then win. EMAIL_REQUIRE_FROM_DOMAIN is
    # left to the case (absent -> module default "sunbizfunding.com"; the
    # opt-out case sets it to "").
    for k in ("GMAIL_USER", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"):
        env[k] = ""
    env.pop("EMAIL_REQUIRE_FROM_DOMAIN", None)
    env.update(env_overrides)
    out = subprocess.run(
        [sys.executable, "-c", SNIPPET], env=env, capture_output=True, text=True
    )
    # The markers are printed to stdout; logging goes to stderr — read stdout only.
    for tok in ("SENT", "REFUSED", "FALSE"):
        if tok in out.stdout:
            return tok
    return out.stdout.strip()


CASES = [
    ("SunBiz sender via GMAIL_USER", {"GMAIL_USER": "submissions@sunbizfunding.com", "GMAIL_APP_PASSWORD": "x"}, "SENT"),
    ("SunBiz sender via GMAIL_ADDRESS", {"GMAIL_ADDRESS": "alex@sunbizfunding.com", "GMAIL_APP_PASSWORD": "x"}, "SENT"),
    ("operator personal Gmail is refused", {"GMAIL_ADDRESS": "conaugh@oasisai.work", "GMAIL_APP_PASSWORD": "x"}, "REFUSED"),
    ("unset sender is refused", {}, "REFUSED"),
    ("subdomain sender is refused", {"GMAIL_ADDRESS": "attacker@mail.sunbizfunding.com", "GMAIL_APP_PASSWORD": "x"}, "REFUSED"),
    ("look-alike domain is refused", {"GMAIL_ADDRESS": "x@evilsunbizfunding.com", "GMAIL_APP_PASSWORD": "x"}, "REFUSED"),
    ("double-@ sender is refused", {"GMAIL_ADDRESS": "a@b@sunbizfunding.com", "GMAIL_APP_PASSWORD": "x"}, "REFUSED"),
    ("explicit opt-out allows any sender", {"GMAIL_ADDRESS": "conaugh@oasisai.work", "EMAIL_REQUIRE_FROM_DOMAIN": ""}, "SENT"),
]


def main():
    failures = 0
    for name, env, expected in CASES:
        got = run(env)
        ok = got == expected
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: expected {expected}, got {got}")
        if not ok:
            failures += 1
    if failures:
        print(f"\n{failures} failure(s)")
        sys.exit(1)
    print(f"\nAll {len(CASES)} identity-guard cases passed.")


if __name__ == "__main__":
    main()
