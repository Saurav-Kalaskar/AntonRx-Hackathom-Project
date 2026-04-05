import os
from pathlib import Path


def load_env_once() -> None:
    """Load environment variables from project-level .env exactly once."""
    if os.environ.get("_APP_ENV_LOADED") == "1":
        return

    root_env = Path(__file__).resolve().parent.parent / ".env"
    backend_env = Path(__file__).resolve().parent / ".env"

    for env_path in (root_env, backend_env):
        if not env_path.exists():
            continue

        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            # Keep explicit shell exports as highest priority.
            os.environ.setdefault(key, value)

    os.environ["_APP_ENV_LOADED"] = "1"
