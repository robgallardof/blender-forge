"""Real test of the Docker image against a real headless Blender on the host (standard library only).

A headless Blender with the bridge (addon/serve.py) runs on the host with a temporary token and a free
port. The container then reaches it like it would reach the Blender you use every day:

- Docker Desktop (Windows/macOS): BLENDER_FORGE_BRIDGE_HOST=host.docker.internal;
- Linux: --network host and BLENDER_FORGE_BRIDGE_HOST=127.0.0.1.

Checks: stdio handshake; forge_status, create_object, render_still and export_file through the bridge, with
the render and the .glb landing in the host folder mounted at /work (BLENDER_FORGE_PATH_MAP); compose over
HTTP with a token on a free port, /healthz and an authorised MCP call. Everything temporary is removed.

    python scripts/test_docker.py
"""
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORGE = ROOT / "mcp" / "blender-forge"
IMAGE = "blender-forge:local"
LINUX = platform.system() == "Linux"
sys.path.insert(0, str(FORGE / "src"))
from blender_forge.client import find_blender  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run(*args, env=None, timeout=1800):
    out = subprocess.run(args, env=env, text=True, capture_output=True, timeout=timeout, encoding="utf-8")
    if out.returncode:
        raise RuntimeError(f"failed {' '.join(map(str, args))}:\n{out.stdout}\n{out.stderr}")
    return out.stdout


def start_blender(config_file):
    exe = find_blender()
    if exe is None:
        raise SystemExit("Blender not found (set BLENDER_FORGE_BLENDER)")
    env = {**os.environ, "BLENDER_FORGE_CONFIG": str(config_file)}
    proc = subprocess.Popen([str(exe), "-b", "--factory-startup", "--python",
                             str(FORGE / "src" / "blender_forge" / "addon" / "serve.py")],
                            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = json.loads(config_file.read_text())["port"]
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            return proc
        except OSError:
            assert proc.poll() is None, "Blender exited before the bridge opened"
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("bridge did not open")


class Stdio:
    """A minimal MCP client over `docker run -i` (newline-delimited JSON-RPC)."""

    def __init__(self, args):
        self.proc = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, encoding="utf-8")
        self.next = 1

    def send(self, message):
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def request(self, method, params):
        ident, self.next = self.next, self.next + 1
        self.send({"jsonrpc": "2.0", "id": ident, "method": method, "params": params})
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("server closed stdout:\n" + self.proc.stderr.read())
            reply = json.loads(line)
            if reply.get("id") == ident:
                return reply

    def tool(self, name, arguments=None):
        reply = self.request("tools/call", {"name": name, "arguments": arguments or {}})
        content = reply["result"]["content"]
        return json.loads(content[0]["text"]), content

    def close(self):
        self.proc.stdin.close()
        self.proc.wait(30)


def stdio_check(work, config_file, token_port):
    bridge_host = "127.0.0.1" if LINUX else "host.docker.internal"
    args = ["docker", "run", "--rm", "-i",
            *(["--network", "host"] if LINUX else ["--add-host", "host.docker.internal:host-gateway"]),
            "-e", f"BLENDER_FORGE_BRIDGE_HOST={bridge_host}",
            "-e", f"BLENDER_FORGE_PATH_MAP=/work={work.as_posix()}",
            "-v", f"{work.as_posix()}:/work",
            "-v", f"{config_file.as_posix()}:/config/bridge.json:ro",
            "-v", f"{ROOT.as_posix()}:/workspace:ro",
            "--user", f"{os.getuid()}:{os.getgid()}" if hasattr(os, "getuid") else "10001:10001",
            IMAGE]
    client = Stdio(args)
    try:
        init = client.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                             "clientInfo": {"name": "docker-test", "version": "1"}})
        assert init["result"]["serverInfo"]["name"] == "blender-forge", init
        client.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        resources = client.request("resources/list", {})["result"]["resources"]
        assert any(r["uri"] == "skill://blender-forge" for r in resources), "skills not served from /workspace"
        status, _ = client.tool("forge_status")
        assert status.get("blender", "").startswith(("4.", "5.")), status
        client.tool("new_scene", {"confirm": True})
        cube, _ = client.tool("create_object", {"kind": "monkey", "name": "DockerMonkey"})
        assert cube["name"] == "DockerMonkey", cube
        client.tool("add_camera", {"look_at": "DockerMonkey", "location": [0, -5, 1]})
        client.tool("render_settings", {"engine": "workbench", "resolution": [160, 120]})
        shot, content = client.tool("render_still")
        assert shot["path"].startswith("/work/"), shot
        assert (work / shot["path"][len("/work/"):]).is_file(), "render did not land in the host folder"
        assert any(c["type"] == "image" for c in content), "render_still returned no image"
        glb, _ = client.tool("export_file", {"path": "/work/monkey.glb"})
        assert (work / "monkey.glb").stat().st_size > 1000 and glb["path"] == "/work/monkey.glb", glb
    finally:
        client.close()
    print("stdio: ok (status, model, render and export through the host bridge)")


def http_check(work, config_file):
    token, port = secrets.token_hex(32), free_port()
    env = {**os.environ, "BLENDER_FORGE_MCP_TOKEN": token, "FORGE_WORK": work.as_posix(),
           "BLENDER_FORGE_CONFIG_FILE": config_file.as_posix(), "BLENDER_FORGE_PORT": str(port),
           "BLENDER_FORGE_WORKSPACE": ROOT.as_posix(), "COMPOSE_PROJECT_NAME": "blender-forge-test"}
    if hasattr(os, "getuid"):
        env["BLENDER_FORGE_USER"] = f"{os.getuid()}:{os.getgid()}"
    files = ["-f", "compose.yaml"] + (["-f", "compose.linux.yaml"] if LINUX else [])
    run("docker", "compose", *files, "up", "-d", "--wait", env=env, timeout=600)
    try:
        base = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(base + "/healthz", timeout=10) as r:
            assert r.status == 200
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                           "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "1"}}}).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        try:
            urllib.request.urlopen(urllib.request.Request(base + "/mcp", body, headers), timeout=10)
            raise AssertionError("HTTP accepted a request without a token")
        except urllib.error.HTTPError as err:
            assert err.code == 401
        req = urllib.request.Request(base + "/mcp", body, {**headers, "Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=20) as r:
            assert r.status == 200 and b"blender-forge" in r.read()
    finally:
        run("docker", "compose", *files, "down", "--remove-orphans", env=env, timeout=300)
    print("http: ok (compose healthy, token required, MCP answers)")


def main():
    run("docker", "build", "-t", IMAGE, str(ROOT), timeout=1800)
    with tempfile.TemporaryDirectory(prefix="blender-forge-docker-") as tmp:
        tmp = Path(tmp)
        work = tmp / "work"
        work.mkdir()
        os.chmod(work, 0o777)
        config_file = tmp / "bridge.json"
        config_file.write_text(json.dumps({"port": free_port(), "token": secrets.token_hex(32)}))
        os.chmod(config_file, 0o644)
        blender = start_blender(config_file)
        try:
            stdio_check(work, config_file, None)
            http_check(work, config_file)
        finally:
            blender.terminate()
            blender.wait(20)
    print("docker: all checks passed")


if __name__ == "__main__":
    main()
