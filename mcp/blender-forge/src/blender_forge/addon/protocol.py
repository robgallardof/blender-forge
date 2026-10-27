"""Bridge wire protocol shared by the MCP server and the Blender extension.

One JSON object per line over a loopback TCP socket. Every request is signed with
HMAC-SHA256 over a canonical encoding, carries a timestamp and a single-use nonce,
and names one operation from an explicit allowlist. Standard library only: this file
ships inside the Blender extension.
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

PROTOCOL_VERSION = 1
MAX_BYTES = 8 * 1024 * 1024
MAX_SKEW_SECONDS = 60
DEFAULT_PORT = 9877


def config_path():
    """Where the shared token lives. Both sides read the same file."""
    override = os.environ.get("BLENDER_FORGE_CONFIG")
    return Path(override).expanduser() if override else Path.home() / ".config" / "blender-forge" / "bridge.json"


def load_config(create=False):
    """Read {port, token}. With create=True a missing file gets a fresh random token."""
    path = config_path()
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("token"), str) or len(data["token"]) < 32:
            raise ValueError(f"{path}: token missing or too short")
        data.setdefault("port", DEFAULT_PORT)
        return data
    if not create:
        raise FileNotFoundError(f"{path} not found; run blender-forge-install or open Blender with the extension")
    data = {"port": int(os.environ.get("BLENDER_FORGE_PORT", DEFAULT_PORT)), "token": secrets.token_hex(32)}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return data


def canonical(message):
    """Signed bytes: every field except the signature, sorted, compact."""
    body = {k: v for k, v in message.items() if k != "signature"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sign_request(token, message):
    return hmac.new(token.encode("utf-8"), canonical(message), hashlib.sha256).hexdigest()


def new_request(token, operation, arguments):
    message = {"protocol": PROTOCOL_VERSION, "id": secrets.token_hex(12), "timestamp": int(time.time()),
               "nonce": secrets.token_urlsafe(18), "operation": operation, "arguments": arguments}
    message["signature"] = sign_request(token, message)
    return message


class ReplayGuard:
    """Rejects stale, future-dated or reused requests."""

    def __init__(self, skew=MAX_SKEW_SECONDS):
        self.skew, self.seen = skew, {}

    def check(self, message, now=None):
        now = time.time() if now is None else now
        stamp = message.get("timestamp")
        if not isinstance(stamp, int) or abs(now - stamp) > self.skew:
            return "STALE_REQUEST"
        nonce = message.get("nonce")
        if not isinstance(nonce, str) or not nonce or nonce in self.seen:
            return "REPLAYED_REQUEST"
        self.seen = {n: t for n, t in self.seen.items() if now - t <= self.skew}
        self.seen[nonce] = now
        return None


def verify(token, message, guard, allowed):
    """Return an error code, or None when the request may run."""
    if not isinstance(message, dict) or message.get("protocol") != PROTOCOL_VERSION:
        return "PROTOCOL_MISMATCH"
    signature = message.get("signature")
    if not isinstance(signature, str) or not hmac.compare_digest(signature, sign_request(token, message)):
        return "BAD_SIGNATURE"
    if message.get("operation") not in allowed:
        return "UNKNOWN_OPERATION"
    if not isinstance(message.get("arguments"), dict):
        return "BAD_ARGUMENTS"
    return guard.check(message)
