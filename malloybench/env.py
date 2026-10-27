"""Loads provider API keys from a dotenv file without overriding the environment."""

from __future__ import annotations

import os
from pathlib import Path


def default_env_file() -> Path:
    """A .env beside the benchmark, else the app's .env of the repository it was developed in."""
    root = Path(__file__).resolve().parent.parent
    return next((p for p in (root / ".env", root.parent.parent / "app" / ".env") if p.exists()), root / ".env")


def load_env(path: str | Path) -> list[str]:
    """Set each KEY=value from `path` that is not already set; return the names set."""
    loaded = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value
            loaded.append(name)
    return loaded
