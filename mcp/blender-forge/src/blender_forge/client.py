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


class PathMap:
    """Container <-> host path prefixes for Docker, from BLENDER_FORGE_PATH_MAP="/work=C:/Users/me/3d;...".

    Blender runs on the host, so every path sent to it is rewritten to the host form, and every path in
    its replies is rewritten back so the server (in the container) can read renders and exports.
    """

    def __init__(self, pairs=()):
        self.pairs = [(c.rstrip("/"), h.rstrip("/\\")) for c, h in pairs]

    @classmethod
    def from_env(cls):
        raw = os.environ.get("BLENDER_FORGE_PATH_MAP", "")
        pairs = []
        for item in filter(None, (p.strip() for p in raw.split(";"))):
            container, sep, host = item.partition("=")
            if not sep or not container.startswith("/") or not host:
                raise ForgeError(f"BLENDER_FORGE_PATH_MAP entry {item!r} must look like /work=C:/host/folder",
                                 "BAD_PATH_MAP")
            pairs.append((container, host))
        return cls(pairs)

    def __bool__(self):
        return bool(self.pairs)

    @staticmethod
    def _swap(value, src, dst, sep):
        norm = value.replace("\\", "/")
        src_n = src.replace("\\", "/")
        if norm == src_n or norm.lower().startswith(src_n.lower() + "/"):
            rest = norm[len(src_n):].lstrip("/")
            return dst + (sep + rest.replace("/", sep) if rest else "")
        return None

    def _walk(self, value, direction):
        if isinstance(value, dict):
            return {k: self._walk(v, direction) for k, v in value.items()}
        if isinstance(value, list):
            return [self._walk(v, direction) for v in value]
        if isinstance(value, str):
            for container, host in self.pairs:
                if direction == "host":
                    sep = "\\" if ":" in host[:3] else "/"
                    hit = self._swap(value, container, host, sep)
                else:
                    hit = self._swap(value, host, container, "/")
                if hit is not None:
                    return hit
        return value

    def to_host(self, value):
        return self._walk(value, "host") if self.pairs else value

    def to_container(self, value):
        return self._walk(value, "container") if self.pairs else value

    def scratch(self, *parts):
        """A folder Blender (host) and the server (container) both see; None without a map."""
        if not self.pairs:
            return None
        path = Path(self.pairs[0][0], ".blender-forge", *parts)
        path.mkdir(parents=True, exist_ok=True)
        return str(path).replace("\\", "/")


def bridge_host():
    """The bridge binds to the host loopback; from Docker Desktop that is host.docker.internal."""
    return os.environ.get("BLENDER_FORGE_BRIDGE_HOST") or "127.0.0.1"


class Client:
    def __init__(self, config=None, timeout=None, paths=None):
        self._config = config
        self.timeout = timeout or float(os.environ.get("BLENDER_FORGE_TIMEOUT", 600))
        self.paths = paths if paths is not None else PathMap.from_env()

    @property
    def config(self):
        if self._config is None:
            try:
                self._config = protocol.load_config(create=False)
            except FileNotFoundError as exc:
                raise ForgeError(str(exc), "NOT_CONFIGURED", "Run blender-forge-install once.") from exc
        return self._config

    def call(self, operation, arguments=None, timeout=None):
        message = protocol.new_request(self.config["token"], operation, self.paths.to_host(arguments or {}))
        raw = (json.dumps(message, allow_nan=False) + "\n").encode("utf-8")
        if len(raw) > protocol.MAX_BYTES:
            raise ForgeError("request too large", "REQUEST_TOO_LARGE")
        try:
            with socket.create_connection((bridge_host(), int(self.config["port"])), timeout=5) as conn:
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
        return self.paths.to_container(reply.get("result"))

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
