"""The extension builds, installs into an isolated Blender user folder, and its bridge answers."""
import json
import os
import socket
import subprocess
import time

import pytest

from blender_forge import install
from blender_forge.client import Client, find_blender

BLENDER = find_blender()
pytestmark = [pytest.mark.blender, pytest.mark.skipif(BLENDER is None, reason="Blender not installed")]


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_install_enable_and_ping_the_installed_extension(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("BLENDER_USER_RESOURCES", str(tmp_path / "blender-user"))
    cfg = tmp_path / "bridge.json"
    monkeypatch.setenv("BLENDER_FORGE_CONFIG", str(cfg))
    cfg.write_text(json.dumps({"port": free_port(), "token": "i" * 64}), encoding="utf-8")

    assert install.main([]) == 0
    present, listing = install.installed(BLENDER)
    assert present, listing

    # Load the installed copy (not the source tree) and start its bridge.
    script = ("import bpy, time, importlib\n"
              "mod = importlib.import_module('bl_ext.user_default.blender_forge_bridge')\n"
              "mod.start()\n"
              "end = time.time() + 40\n"
              "while time.time() < end: time.sleep(0.1)\n")
    proc = subprocess.Popen([str(BLENDER), "-b", "--python-expr", script], env=os.environ.copy(),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        client = Client(json.loads(cfg.read_text(encoding="utf-8")))
        deadline, pong = time.time() + 40, None
        while pong is None and time.time() < deadline:
            pong = client.reachable()
            time.sleep(0.3)
        assert pong and "build_scene" not in pong["operations"] and "look" in pong["operations"]
        assert "run_python" not in pong["operations"]
    finally:
        proc.kill()
        proc.wait(10)

    assert install.main(["--remove"]) == 0
    assert not install.installed(BLENDER)[0]
