"""Shared observable progress. A liveness pulse is not a promise of I/O progress."""

from __future__ import annotations
import json
import sys
import threading
import time
from collections import deque
from .util import Problem, now, sizes


class Progress:
    def __init__(self, callback=None):
        self.callback = callback
        self.cancelled = threading.Event()
        self.lock = threading.RLock()
        self.started = time.monotonic()
        self.finished = None
        self.phase_started = self.started
        self.changed = self.started
        self.name, self.unit, self.done, self.total, self.path = "Ready", "items", 0, None, ""
        self.samples = deque(maxlen=100)
        self.events = deque(maxlen=200)
        self.last_emit = 0.0

    def check(self):
        if self.cancelled.is_set():
            raise Problem(
                "CANCELLED",
                "Operation cancelled; committed packages are reusable and partials were retained",
            )

    def finish(self):
        """Freeze timing once work terminates; later polling must not extend a job."""
        with self.lock:
            if self.finished is None:
                self.finished = time.monotonic()

    def phase(self, name, total=None, unit="items"):
        with self.lock:
            self.name, self.done, self.total, self.unit = name, 0, total, unit
            self.phase_started = self.changed = time.monotonic()
            self.samples.clear()
            self.samples.append((self.changed, 0))
        self.event("INFO", "PHASE", phase=name, total=total, unit=unit)
        self.emit(True)

    def update(self, done, path=""):
        self.check()
        with self.lock:
            if done != self.done:
                self.changed = time.monotonic()
                self.samples.append((self.changed, done))
            self.done, self.path = done, path
        self.emit()

    def advance(self, n, path=""):
        with self.lock:
            self.update(self.done + n, path)

    def event(self, level, code, **fields):
        with self.lock:
            self.events.append({"time": now(), "level": level, "code": code, **fields})

    def state(self):
        with self.lock:
            t = self.finished if self.finished is not None else time.monotonic()
            rate = None
            if len(self.samples) > 1:
                a, b = self.samples[0], self.samples[-1]
                if b[0] > a[0]:
                    rate = (b[1] - a[1]) / (b[0] - a[0])
            # Do not let a stale throughput estimate look like a progressing device.
            stale = t - self.changed
            eta = (
                max(0, self.total - self.done) / rate
                if self.finished is None and self.total is not None and rate and stale < 10
                else None
            )
            return {
                "phase": self.name,
                "unit": self.unit,
                "done": self.done,
                "total": self.total,
                "elapsed_seconds": round(t - self.started, 2),
                "phase_seconds": round(t - self.phase_started, 2),
                "rate": rate,
                "eta_seconds": eta,
                "idle_seconds": round(stale, 2),
                "path": self.path,
                "cancel_requested": self.cancelled.is_set(),
                "finished": self.finished is not None,
                "events": list(self.events),
            }

    def emit(self, force=False):
        t = time.monotonic()
        if self.callback and (force or t - self.last_emit >= 0.5):
            self.last_emit = t
            self.callback(self.state())


class ConsoleProgress:
    def __init__(self, quiet=False):
        self.quiet = quiet
        self.last = 0.0
        self.stop = threading.Event()
        self.progress = Progress(self.output)
        self.thread = threading.Thread(target=self.heartbeat, daemon=True)

    def output(self, state):
        if self.quiet:
            return
        t = time.monotonic()
        if t - self.last < 1:
            return
        self.last = t
        done, total = state["done"], state["total"]
        fraction = min(1, done / total) if total else None
        bar = (
            "[" + ("=" * int(20 * fraction)).ljust(20) + "]"
            if fraction is not None
            else "[ working; total=?   ]"
        )
        amount = sizes(done) if state["unit"] == "bytes" else f"{done:,} {state['unit']}"
        eta = f"{state['eta_seconds']:.0f}s" if state["eta_seconds"] is not None else "?"
        # JSON escaping prevents control sequences in paths from forging console output.
        path = json.dumps(state["path"], ensure_ascii=True)[1:-1]
        print(
            f"{time.strftime('%H:%M:%S')} +{state['elapsed_seconds']:7.1f}s {state['phase'][:14]:14} {bar} {amount:28} ETA {eta:>7} {path}",
            file=sys.stderr,
            flush=True,
        )

    def heartbeat(self):
        while not self.stop.wait(2):
            self.progress.emit(True)

    def __enter__(self):
        self.thread.start()
        return self.progress

    def __exit__(self, *args):
        self.progress.finish()
        self.stop.set()
        self.thread.join(timeout=3)
