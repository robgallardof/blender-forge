"""Talks to the bridge, and finds or starts Blender when no bridge is listening."""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from .addon import protocol

ADDON_DIR = Path(__file__).resolve().parent / "addon"


class ForgeError(Exception):
    def __init__(self, message, code="FORGE_ERROR", hint=None):
        super().__init__(message)
        self.code, self.hint = code, hint

    def as_dict(self):
        out = {"error": {"code": self.code, "message": str(self)}}
        if self.hint:
            out["error"]["hint"] = self.hint
        return out


NOT_RUNNING = ("Open Blender with the blender-forge extension enabled (it listens on start), "
               "or call start_headless to run Blender in the background.")


class Client:
    def __init__(self, config=None, timeout=None):
        self._config = config
        self.timeout = timeout or float(os.environ.get("BLENDER_FORGE_TIMEOUT", 600))

    @property
    def config(self):
        if self._config is None:
            try:
                self._config = protocol.load_config(create=False)
            except FileNotFoundError as exc:
                raise ForgeError(str(exc), "NOT_CONFIGURED", "Run blender-forge-install once.") from exc
        return self._config

    def call(self, operation, arguments=None, timeout=None):
        message = protocol.new_request(self.config["token"], operation, arguments or {})
        raw = (json.dumps(message, allow_nan=False) + "\n").encode("utf-8")
        if len(raw) > protocol.MAX_BYTES:
            raise ForgeError("request too large", "REQUEST_TOO_LARGE")
        try:
            with socket.create_connection(("127.0.0.1", int(self.config["port"])), timeout=5) as conn:
                conn.settimeout(timeout or self.timeout)
                conn.sendall(raw)
                line = conn.makefile("rb").readline(protocol.MAX_BYTES + 1)
        except (ConnectionRefusedError, socket.timeout, OSError) as exc:
            raise ForgeError(f"Blender bridge not reachable on port {self.config['port']} ({exc})",
                             "BRIDGE_OFFLINE", NOT_RUNNING) from exc
        try:
            reply = json.loads(line)
        except ValueError as exc:
            raise ForgeError("bridge sent invalid JSON", "BRIDGE_PROTOCOL_ERROR") from exc
        if reply.get("id") != message["id"]:
            raise ForgeError("bridge reply did not match the request", "BRIDGE_PROTOCOL_ERROR")
        if not reply.get("ok"):
            err = reply.get("error") or {}
            raise ForgeError(err.get("message", "bridge refused the request"), err.get("code", "BRIDGE_REFUSED"))
        return reply.get("result")

    def reachable(self):
        try:
            return self.call("ping", timeout=5)
        except ForgeError:
            return None


def find_blender():
    """Explicit setting first, then PATH, then the usual install folders (newest first)."""
    explicit = os.environ.get("BLENDER_FORGE_BLENDER") or os.environ.get("BLENDER_PATH")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    found = shutil.which("blender")
    if found:
        return Path(found)
    roots = []
    if sys.platform == "win32":
        roots = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Blender Foundation"]
        candidates = sorted((p / "blender.exe" for root in roots if root.is_dir() for p in root.iterdir()),
                            key=lambda p: p.parent.name, reverse=True)
    elif sys.platform == "darwin":
        candidates = [Path("/Applications/Blender.app/Contents/MacOS/Blender")]
    else:
        candidates = [Path("/usr/bin/blender"), Path("/snap/bin/blender"), Path.home() / "blender" / "blender"]
    return next((c for c in candidates if c.is_file()), None)


class Headless:
    """A background Blender running serve.py; owned by this MCP server process."""

    def __init__(self):
        self.proc = None

    def start(self, client, blend_file=None, wait=60):
        if client.reachable():
            return {"started": False, "reason": "a bridge is already listening"}
        exe = find_blender()
        if exe is None:
            raise ForgeError("Blender not found", "BLENDER_NOT_FOUND",
                             "Install Blender or set BLENDER_FORGE_BLENDER to blender(.exe).")
        protocol.load_config(create=True)
        client._config = None
        args = [str(exe), "-b"]
        if blend_file:
            args.append(str(Path(blend_file).expanduser().resolve()))
        args += ["--factory-startup", "--python", str(ADDON_DIR / "serve.py")]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, creationflags=flags)
        deadline = time.time() + wait
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise ForgeError(f"Blender exited with code {self.proc.returncode}", "HEADLESS_FAILED")
            pong = client.reachable()
            if pong:
                return {"started": True, "pid": self.proc.pid, "blender": str(exe),
                        "operations": len(pong.get("operations", []))}
            time.sleep(0.5)
        self.stop()
        raise ForgeError("headless Blender did not open the bridge in time", "HEADLESS_TIMEOUT")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        stopped = self.proc is not None
        self.proc = None
        return {"stopped": stopped}
