"""A durable record of every model call's cost, with a hard spending cap.

Every call is appended to one JSONL file shared by all runs, so the cap counts what was
spent across runs, not only in the current one. A call is refused before it is made once
the recorded spend plus a reserve for that call would pass the cap. The file is read again
before every reservation, so runs going at the same time share one cap. (Calls another
process has in flight are not seen until it records them.)
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    def __init__(self, path: str | Path, cap_usd: float):
        self.path = Path(path)
        self.cap_usd = cap_usd
        self._lock = threading.Lock()
        self.spent_usd = 0.0
        self.reserved_usd = 0.0  # calls in flight, so parallel workers cannot jointly pass the cap
        self._offset = 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._refresh()

    def _refresh(self) -> None:
        """Count the lines appended since the last read, by this process or any other."""
        if not self.path.exists():
            return
        with self.path.open("rb") as f:
            f.seek(self._offset)
            chunk = f.read()
        end = chunk.rfind(b"\n") + 1  # a line still being written is counted on the next read
        for line in chunk[:end].splitlines():
            if line.strip():
                self.spent_usd += float(json.loads(line).get("cost_usd", 0.0))
        self._offset += end

    def reserve(self, estimate_usd: float) -> None:
        with self._lock:
            self._refresh()
            if self.spent_usd + self.reserved_usd + estimate_usd > self.cap_usd:
                raise BudgetExceeded(
                    f"spent ${self.spent_usd:.2f} (+${self.reserved_usd:.2f} in flight) of ${self.cap_usd:.2f}; "
                    f"next call reserves ${estimate_usd:.2f}"
                )
            self.reserved_usd += estimate_usd

    def release(self, estimate_usd: float) -> None:
        with self._lock:
            self.reserved_usd = max(0.0, self.reserved_usd - estimate_usd)

    def record(self, entry: dict) -> None:
        with self._lock:
            with self.path.open("a") as f:
                f.write(json.dumps({"ts": time.time(), **entry}) + "\n")
            self._refresh()
