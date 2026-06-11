"""
Sun Biz Agent hosted API surface.

Exposes the small production contract the command center already expects:
- GET /health
- GET /status
- POST /sms/send
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from doctor import build_report, load_env_file
from sms_engine import send_sms, status as sms_status

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env.agents"

app = FastAPI(title="Sun Biz Agent API", version="1.2.0")


class SMSRequest(BaseModel):
    to: str = Field(..., description="Recipient in E.164 format")
    body: str = Field(..., min_length=1, max_length=1600)
    tenant_slug: str = Field(default="sun")
    client_profile: str = Field(default="sun")
    provider: str = Field(default="auto")
    merge_vars: dict[str, Any] | None = None


def _resolve_env(key: str) -> str:
    env = load_env_file(ENV_PATH)
    return os.environ.get(key) or env.get(key, "")


def _get_hmac_secret() -> str:
    return _resolve_env("SUNBIZ_AGENT_HMAC_SECRET")


def _clean_signature(signature: str) -> str:
    if signature.startswith("sha256="):
        return signature.split("=", 1)[1]
    return signature


def _require_oasis_signature(request: Request, raw_body: bytes, body: SMSRequest) -> None:
    secret = _get_hmac_secret()
    if not secret:
        return

    timestamp = request.headers.get("x-oasis-timestamp")
    signature = request.headers.get("x-oasis-signature")
    header_tenant = request.headers.get("x-oasis-tenant-slug")
    header_profile = request.headers.get("x-oasis-client-profile")

    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="signed request required")

    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="invalid x-oasis-timestamp") from exc

    if abs(int(time.time()) - timestamp_int) > 60:
        raise HTTPException(status_code=401, detail="request timestamp expired")

    if header_tenant and header_tenant != body.tenant_slug:
        raise HTTPException(status_code=401, detail="tenant slug mismatch")
    if header_profile and header_profile != body.client_profile:
        raise HTTPException(status_code=401, detail="client profile mismatch")

    signed_payload = f"{timestamp}.{raw_body.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    provided = _clean_signature(signature)
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="invalid signature")


@app.get("/health")
def health(deep: bool = False) -> dict[str, Any]:
    return build_report(include_live_checks=deep)


@app.get("/status")
def status() -> dict[str, Any]:
    doctor = build_report(include_live_checks=False)
    return {
        "ok": doctor["verdict"] != "UNHEALTHY",
        "verdict": doctor["verdict"],
        "checked_at": doctor["checked_at"],
        "sms": sms_status(),
    }


@app.post("/sms/send")
async def sms_send(body: SMSRequest, request: Request) -> dict[str, Any]:
    raw_body = await request.body()
    _require_oasis_signature(request, raw_body, body)

    result = send_sms(
        to=body.to,
        body=body.body,
        provider=body.provider,
        merge_vars=body.merge_vars,
    )
    payload = result.to_dict()
    payload["tenant_slug"] = body.tenant_slug
    payload["client_profile"] = body.client_profile

    if result.ok:
        return payload
    if result.status == "validation_error":
        raise HTTPException(status_code=400, detail=payload)
    raise HTTPException(status_code=503, detail=payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Sun Biz Agent hosted API")
    parser.add_argument("--host", default=_resolve_env("SUNBIZ_AGENT_API_HOST") or "0.0.0.0")
    parser.add_argument("--port", type=int, default=int(_resolve_env("SUNBIZ_AGENT_API_PORT") or "8787"))
    args = parser.parse_args(argv)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
