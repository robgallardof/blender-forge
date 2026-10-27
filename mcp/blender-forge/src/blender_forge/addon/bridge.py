"""Loopback TCP bridge that runs signed operations on Blender's main thread.

A socket thread accepts one request per connection, verifies it and queues it. The
main thread executes queued work: from a bpy.app.timers callback in the UI, or from a
blocking loop when Blender runs headless (`blender -b --python serve.py`).
"""
import json
import os
import queue
import socket
import threading
import traceback

from . import protocol

_jobs = queue.Queue()


class Job:
    def __init__(self, operation, arguments):
        self.operation, self.arguments = operation, arguments
        self.done = threading.Event()
        self.result, self.error = None, None


def python_enabled(config):
    return bool(config.get("allow_python")) or os.environ.get("BLENDER_FORGE_ALLOW_PYTHON") == "1"


class Bridge:
    def __init__(self, config, timeout=600):
        from . import ops  # bpy lives here; keep protocol importable without Blender
        self.ops = ops
        self.config = config
        self.timeout = timeout
        self.allowed = set(ops.OPERATIONS) | {"ping"}
        if not python_enabled(config):
            self.allowed.discard("run_python")
        self.guard = protocol.ReplayGuard()
        self.sock = None
        self.thread = None
        self.running = False

    # -------------------------------------------------- socket side

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", int(self.config["port"])))
        self.sock.listen(8)
        self.sock.settimeout(0.5)
        self.running = True
        self.thread = threading.Thread(target=self._accept, name="blender-forge-bridge", daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

    def _accept(self):
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        with conn:
            conn.settimeout(30)
            try:
                raw = conn.makefile("rb").readline(protocol.MAX_BYTES + 1)
                reply = self._handle(raw)
            except Exception as exc:  # never let a bad client kill the thread
                reply = {"id": None, "ok": False, "error": {"code": "BRIDGE_ERROR", "message": str(exc)}}
            try:
                conn.sendall((json.dumps(reply, default=str) + "\n").encode("utf-8"))
            except OSError:
                pass

    def _handle(self, raw):
        if len(raw) > protocol.MAX_BYTES or not raw.endswith(b"\n"):
            return {"id": None, "ok": False, "error": {"code": "REQUEST_TOO_LARGE", "message": "request too large"}}
        try:
            message = json.loads(raw)
        except ValueError:
            return {"id": None, "ok": False, "error": {"code": "BAD_JSON", "message": "invalid JSON"}}
        ident = message.get("id") if isinstance(message, dict) else None
        problem = protocol.verify(self.config["token"], message, self.guard, self.allowed)
        if problem:
            return {"id": ident, "ok": False, "error": {"code": problem, "message": problem.replace("_", " ").lower()}}
        if message["operation"] == "ping":
            return {"id": ident, "ok": True, "result": {"pong": True, "operations": sorted(self.allowed)}}
        arguments = dict(message["arguments"])
        arguments["_python_enabled"] = "run_python" in self.allowed
        job = Job(message["operation"], arguments)
        _jobs.put(job)
        if not job.done.wait(self.timeout):
            return {"id": ident, "ok": False, "error": {"code": "TIMEOUT", "message": "Blender did not answer in time"}}
        if job.error:
            return {"id": ident, "ok": False, "error": job.error}
        return {"id": ident, "ok": True, "result": job.result}

    # -------------------------------------------------- main-thread side

    def pump(self, limit=8):
        """Run queued jobs. Call only from Blender's main thread."""
        for _ in range(limit):
            try:
                job = _jobs.get_nowait()
            except queue.Empty:
                return
            try:
                job.result = self.ops.OPERATIONS[job.operation](job.arguments)
            except self.ops.OpError as exc:
                job.error = {"code": exc.code, "message": str(exc)}
            except Exception as exc:
                job.error = {"code": "BLENDER_ERROR", "message": f"{type(exc).__name__}: {exc}",
                             "trace": traceback.format_exc(limit=4)[-2000:]}
            finally:
                job.done.set()

    def serve_blocking(self, stop_event=None):
        """Headless mode: this thread is Blender's main thread."""
        import time
        while self.running and not (stop_event and stop_event.is_set()):
            self.pump()
            time.sleep(0.02)
