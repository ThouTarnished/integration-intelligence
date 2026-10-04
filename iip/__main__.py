"""Command-line entry point.

    python -m iip              start the platform on http://127.0.0.1:8000
    python -m iip --reset      wipe the database and re-seed fresh demo data first
    python -m iip --reload     auto-restart on code changes (development)
"""
from __future__ import annotations

import argparse

import uvicorn

from .config import settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m iip", description="Integration Intelligence Platform")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--reload", action="store_true", help="restart automatically when code changes")
    parser.add_argument("--reset", action="store_true", help="wipe and re-seed the database before starting")
    args = parser.parse_args()

    if args.reset:
        from .database import SessionLocal, reset_db
        from .seed import seed

        reset_db()
        with SessionLocal() as db:
            seed(db)
        print("Database reset with fresh synthetic data.")

    print(f"\n  IIP dashboard  ->  http://{args.host}:{args.port}\n  API docs       ->  http://{args.host}:{args.port}/docs\n")
    uvicorn.run("iip.app:app", host=args.host, port=args.port, reload=args.reload, log_level="warning")


if __name__ == "__main__":
    main()
