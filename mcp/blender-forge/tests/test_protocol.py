"""Bridge protocol: signatures, replay protection, allowlist, config handling."""
import json

import pytest

from blender_forge.addon import protocol

TOKEN = "t" * 64


def test_signed_request_verifies():
    msg = protocol.new_request(TOKEN, "status", {})
    assert protocol.verify(TOKEN, msg, protocol.ReplayGuard(), {"status"}) is None


@pytest.mark.parametrize("mutate,code", [
    (lambda m: m.update(arguments={"x": 1}), "BAD_SIGNATURE"),
    (lambda m: m.update(signature="0" * 64), "BAD_SIGNATURE"),
    (lambda m: m.update(protocol=99), "PROTOCOL_MISMATCH"),
])
def test_tampering_is_rejected(mutate, code):
    msg = protocol.new_request(TOKEN, "status", {})
    mutate(msg)
    assert protocol.verify(TOKEN, msg, protocol.ReplayGuard(), {"status"}) == code


def test_wrong_token_and_unknown_operation():
    msg = protocol.new_request("x" * 64, "status", {})
    assert protocol.verify(TOKEN, msg, protocol.ReplayGuard(), {"status"}) == "BAD_SIGNATURE"
    msg = protocol.new_request(TOKEN, "run_python", {"code": "1"})
    assert protocol.verify(TOKEN, msg, protocol.ReplayGuard(), {"status"}) == "UNKNOWN_OPERATION"


def test_replay_and_stale_requests():
    guard = protocol.ReplayGuard()
    msg = protocol.new_request(TOKEN, "status", {})
    assert protocol.verify(TOKEN, msg, guard, {"status"}) is None
    assert protocol.verify(TOKEN, msg, guard, {"status"}) == "REPLAYED_REQUEST"
    old = protocol.new_request(TOKEN, "status", {})
    old["timestamp"] -= 3600
    old["signature"] = protocol.sign_request(TOKEN, old)
    assert protocol.verify(TOKEN, old, guard, {"status"}) == "STALE_REQUEST"


def test_config_created_once_with_strong_token(tmp_path, monkeypatch):
    path = tmp_path / "bridge.json"
    monkeypatch.setenv("BLENDER_FORGE_CONFIG", str(path))
    with pytest.raises(FileNotFoundError):
        protocol.load_config()
    first = protocol.load_config(create=True)
    assert len(first["token"]) == 64 and first["port"] == protocol.DEFAULT_PORT
    assert protocol.load_config() == first
    path.write_text(json.dumps({"token": "short"}), encoding="utf-8")
    with pytest.raises(ValueError):
        protocol.load_config()
