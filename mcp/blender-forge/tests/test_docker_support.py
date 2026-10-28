"""Pieces the Docker image relies on: path translation and the token-guarded HTTP transport."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from blender_forge.client import ForgeError, PathMap


def test_path_map_round_trip_windows_host():
    pm = PathMap([("/work", "C:/Users/me/3d")])
    sent = pm.to_host({"path": "/work/out/a.glb", "names": ["/work"], "other": "/elsewhere/x", "n": 3})
    assert sent == {"path": "C:/Users/me/3d\\out\\a.glb", "names": ["C:/Users/me/3d"], "other": "/elsewhere/x", "n": 3}
    back = pm.to_container({"path": "C:\\Users\\me\\3d\\out\\a.glb", "views": [{"path": "c:/users/me/3d/v.png"}]})
    assert back == {"path": "/work/out/a.glb", "views": [{"path": "/work/v.png"}]}
    assert not PathMap() and PathMap().to_host({"path": "/work/x"}) == {"path": "/work/x"}


def test_path_map_env_is_validated(monkeypatch):
    monkeypatch.setenv("BLENDER_FORGE_PATH_MAP", "/work=/home/me/3d;/assets=/srv/assets")
    assert PathMap.from_env().pairs == [("/work", "/home/me/3d"), ("/assets", "/srv/assets")]
    monkeypatch.setenv("BLENDER_FORGE_PATH_MAP", "work-without-slash=/x")
    with pytest.raises(ForgeError):
        PathMap.from_env()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(url, body=None, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, headers=headers or {},
                                 method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode()


def test_http_transport_requires_token_blocks_browsers_and_serves_mcp(tmp_path):
    token, port = "h" * 40, free_port()
    env = {**os.environ, "BLENDER_FORGE_MCP_TOKEN": token, "BLENDER_FORGE_CONFIG": str(tmp_path / "none.json")}
    proc = subprocess.Popen([sys.executable, "-m", "blender_forge.server", "--http", "--listen", f"127.0.0.1:{port}"],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while True:
            try:
                if request(base + "/healthz")[0] == 200:
                    break
            except OSError:
                pass
            assert time.time() < deadline, "HTTP server did not start"
            time.sleep(0.3)
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
        accept = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        assert request(base + "/mcp", init, accept)[0] == 401
        assert request(base + "/mcp", init, {**accept, "Authorization": "Bearer wrong"})[0] == 401
        assert request(base + "/mcp", init, {**accept, "Authorization": f"Bearer {token}", "Origin": "https://evil.example"})[0] == 403
        status, body = request(base + "/mcp", init, {**accept, "Authorization": f"Bearer {token}"})
        assert status == 200 and "blender-forge" in body
    finally:
        proc.terminate()
        proc.wait(10)
