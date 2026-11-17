"""Small loopback-only GUI adapter. Exact static routes; same application operations."""

from __future__ import annotations
import concurrent.futures
import json
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from .application import Application, READ_ACTIONS, WRITE_ACTIONS
from .progress import Progress
from .store import remember_workspace
from .util import Problem, canonical, now, require, uid

STATIC = Path(__file__).with_name("static")
ASSETS = {
    "/": "index.html",
    "/bootstrap.js": "bootstrap.js",
    "/app.js": "app.js",
    "/app.css": "app.css",
}


class Tasks:
    def __init__(self, app):
        self.app = app
        self.executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="archivist-worker"
        )
        self.lock = threading.RLock()
        self.items = {}
        self.closed = False

    def submit(self, action, args):
        require(
            action in WRITE_ACTIONS
            or action in ("preflight_build", "preflight_copy", "preflight_restore"),
            "ACTION",
            "Only work/review actions can be queued",
        )
        with self.lock:
            require(not self.closed, "CLOSED", "The local service is stopping")
            require(
                sum(x["state"] in ("QUEUED", "RUNNING") for x in self.items.values()) < 16,
                "QUEUE_FULL",
                "Queue limit reached",
            )
            for key in list(self.items):
                if len(self.items) <= 100:
                    break
                if self.items[key]["state"] not in ("QUEUED", "RUNNING"):
                    del self.items[key]
            ident = uid("task")
            p = Progress()
            record = {
                "id": ident,
                "action": action,
                "state": "QUEUED",
                "created": now(),
                "progress": p,
                "result": None,
                "error": None,
                "app": self.app,
            }
            self.items[ident] = record
            record["future"] = self.executor.submit(self.run, record, args)
            return ident

    def run(self, record, args):
        with self.lock:
            record["state"] = "RUNNING"
        try:
            record["progress"].check()
            record["result"] = record["app"].call(record["action"], args, record["progress"])
            terminal = "COMPLETE"
        except BaseException as exc:
            terminal = "CANCELLED" if getattr(exc, "code", "") == "CANCELLED" else "FAILED"
            record["error"] = (
                exc.record()
                if isinstance(exc, Problem)
                else {"code": type(exc).__name__, "message": str(exc)}
            )
        finally:
            record["progress"].finish()
        with self.lock:
            record["completed"] = now()
            record["state"] = terminal

    def list(self, details=None):
        with self.lock:
            rows = []
            for t in self.items.values():
                if details and t["id"] != details:
                    continue
                r = {k: v for k, v in t.items() if k not in ("future", "progress", "result", "app")}
                r["progress"] = t["progress"].state()
                if details:
                    r["result"] = t["result"]
                rows.append(r)
            return rows

    def cancel(self, ident):
        with self.lock:
            t = self.items.get(ident)
            require(t is not None, "TASK", "Unknown task")
            if t["state"] not in ("QUEUED", "RUNNING"):
                return {"id": ident, "cancel_requested": False, "state": t["state"]}
            t["progress"].cancelled.set()
            if t["state"] == "QUEUED" and t["future"].cancel():
                t["progress"].finish()
                t["completed"] = now()
                t["state"] = "CANCELLED"
                t["error"] = {
                    "code": "CANCELLED",
                    "message": "Queued operation cancelled before it started",
                }
            return {"id": ident, "cancel_requested": True}

    def busy(self):
        with self.lock:
            return any(t["state"] in ("QUEUED", "RUNNING") for t in self.items.values())

    def close(self):
        # Python 3.8 has no shutdown(cancel_futures=...). Cancel queued futures
        # explicitly and keep their observable task records terminal as well.
        with self.lock:
            self.closed = True
            for ident in list(self.items):
                self.cancel(ident)
        self.executor.shutdown(wait=True)


def make_server(app, port=8765):
    token = secrets.token_urlsafe(32)
    tasks = Tasks(app)

    class Handler(BaseHTTPRequestHandler):
        server_version = "Archivist"

        def log_message(self, *args):
            pass

        def valid_host(self):
            return self.headers.get("Host") in (
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            )

        def reply(self, value, status=200):
            raw = canonical(value)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.headers_common(len(raw))
            self.end_headers()
            self.wfile.write(raw)

        def headers_common(self, length):
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            )

        def auth(self, write=False):
            require(self.valid_host(), "HOST", "Unrecognised Host header")
            require(
                secrets.compare_digest(self.headers.get("X-AP20-Token", ""), token),
                "TOKEN",
                "Missing local session token",
            )
            origin = self.headers.get("Origin")
            require(
                origin is None
                or origin
                in (
                    f"http://127.0.0.1:{self.server.server_port}",
                    f"http://localhost:{self.server.server_port}",
                ),
                "ORIGIN",
                "Cross-origin requests are not accepted",
            )
            require(
                self.headers.get("Sec-Fetch-Site") not in ("cross-site",),
                "ORIGIN",
                "Cross-site requests are not accepted",
            )

        def do_GET(self):
            try:
                require(self.valid_host(), "HOST", "Unrecognised Host header")
                path = urllib.parse.urlsplit(self.path).path
                if path in ASSETS:
                    raw = (STATIC / ASSETS[path]).read_bytes()
                    if path == "/":
                        raw = raw.replace(b"__SESSION_TOKEN__", token.encode())
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        {
                            "/": "text/html; charset=utf-8",
                            "/app.js": "text/javascript; charset=utf-8",
                            "/bootstrap.js": "text/javascript; charset=utf-8",
                            "/app.css": "text/css; charset=utf-8",
                        }[path],
                    )
                    self.headers_common(len(raw))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                self.auth()
                if path == "/api/tasks":
                    return self.reply(tasks.list())
                if path.startswith("/api/task/"):
                    value = tasks.list(path.rsplit("/", 1)[-1])
                    require(value, "TASK", "Task not found")
                    return self.reply(value[0])
                if path == "/api/read":
                    q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
                    action = q.get("action", [""])[0]
                    require(action in READ_ACTIONS, "ACTION", "Unsupported read action")
                    raw = q.get("args", ["{}"])[0]
                    require(len(raw) <= 65536, "REQUEST_SIZE", "Read query is too large")
                    return self.reply(tasks.app.call(action, json.loads(raw)))
                return self.reply(
                    {"error": {"code": "NOT_FOUND", "message": "Route not found"}}, 404
                )
            except Exception as exc:
                self.error_response(exc)

        def do_POST(self):
            try:
                self.auth(True)
                require(
                    self.headers.get("Content-Type", "").split(";")[0] == "application/json",
                    "CONTENT_TYPE",
                    "JSON body required",
                )
                n = int(self.headers.get("Content-Length", "0"))
                require(
                    0 < n <= 1024 * 1024, "REQUEST_SIZE", "Request body must be 1 byte to 1 MiB"
                )
                body = json.loads(self.rfile.read(n))
                require(isinstance(body, dict), "BODY", "JSON object required")
                if self.path == "/api/task":
                    return self.reply(
                        {"task_id": tasks.submit(body["action"], body.get("args", {}))}, 202
                    )
                if self.path == "/api/cancel":
                    return self.reply(tasks.cancel(body["id"]))
                if self.path == "/api/preferences":
                    return self.reply(tasks.app.call("set_preferences", body))
                if self.path == "/api/workspace":
                    with tasks.lock:
                        require(
                            not tasks.busy(),
                            "BUSY",
                            "Finish or cancel current work before changing workspace",
                        )
                        candidate = Path(body["path"])
                        require(
                            (candidate / "workspace.sqlite").is_file(),
                            "WORKSPACE",
                            "Choose an existing supported workspace",
                        )
                        tasks.app = Application(candidate)
                        remember_workspace(candidate)
                        return self.reply(tasks.app.call("status"))
                if self.path == "/api/stop":
                    require(
                        not tasks.busy(),
                        "BUSY",
                        "Finish or cancel active work before stopping the service",
                    )
                    self.reply({"stopping": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                self.reply({"error": {"code": "NOT_FOUND", "message": "Route not found"}}, 404)
            except Exception as exc:
                self.error_response(exc)

        def error_response(self, exc):
            problem = (
                exc.record()
                if isinstance(exc, Problem)
                else {"code": type(exc).__name__, "message": str(exc)}
            )
            self.reply(
                {"error": problem},
                403 if getattr(exc, "code", "") in ("TOKEN", "HOST", "ORIGIN") else 400,
            )

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.tasks = tasks
    server.session_token = token
    return server


def serve(app, port=8765, open_browser=True):
    # Never silently attach to an older application or a different workspace.
    server = None
    for candidate in [port] if port == 0 else range(port, port + 10):
        try:
            server = make_server(app, candidate)
            break
        except OSError:
            if port == 0:
                raise
    require(server is not None, "PORT", "No free loopback port in the selected range")
    url = f"http://127.0.0.1:{server.server_port}/"
    print(
        "Archivist\nWorkspace: "
        + str(app.workspace)
        + "\nGUI: "
        + url
        + "\nKeep this process open. Ctrl+C stops it; the GUI also has File → Quit.",
        flush=True,
    )
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.tasks.close()
