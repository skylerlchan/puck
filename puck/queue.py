"""A bug queue. Reports go in; a pool of worker threads pulls them out and runs
the fixer. People can see their position in line ("you're #2")."""
from __future__ import annotations

import queue
import threading
import traceback
from typing import Callable

from .models import Job


class JobQueue:
    def __init__(self, worker_fn: Callable[[Job], None], concurrency: int = 1):
        self._q: "queue.Queue[Job]" = queue.Queue()
        self._worker_fn = worker_fn
        self._concurrency = max(1, concurrency)
        self._order: list[str] = []      # job ids still waiting, in arrival order
        self._lock = threading.Lock()
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for n in range(self._concurrency):
            t = threading.Thread(target=self._loop, name=f"fixer-{n}", daemon=True)
            t.start()
            self._threads.append(t)

    def submit(self, job: Job) -> int:
        """Enqueue and return the 1-based position in line (1 = next up)."""
        with self._lock:
            self._order.append(job.id)
            pos = len(self._order)
        self._q.put(job)
        return pos

    def position(self, job_id: str) -> int:
        with self._lock:
            return self._order.index(job_id) + 1 if job_id in self._order else 0

    def depth(self) -> int:
        with self._lock:
            return len(self._order)

    def join(self) -> None:
        """Block until every submitted job has been processed (for tests)."""
        self._q.join()

    def _loop(self) -> None:
        while True:
            job = self._q.get()
            try:
                self._worker_fn(job)
            except Exception:  # a crash on one job must not kill the worker
                traceback.print_exc()
            finally:
                # keep the job in _order until it's DONE so "#N in line" counts the
                # in-flight jobs ahead of you, not just the still-waiting ones
                with self._lock:
                    if job.id in self._order:
                        self._order.remove(job.id)
                self._q.task_done()
