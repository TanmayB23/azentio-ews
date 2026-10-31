"""python -m api [--port 8000] [--reload]

Settings such as OPENAI_API_KEY can live in a .env file in the project root
(see .env.example). Variables already set in the environment take priority.
"""
import argparse
import os
from pathlib import Path

import uvicorn

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_env_file(path: Path = ENV_FILE) -> list[str]:
    """Load KEY=VALUE lines into os.environ without overriding existing values. Returns the keys loaded."""
    if not path.is_file():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.removeprefix("export ").strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the EWS web app")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true", help="restart on code changes (development)")
    args = ap.parse_args()
    loaded = load_env_file()
    if loaded:
        print(f"Loaded from .env: {', '.join(sorted(loaded))}")
    uvicorn.run("api.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
