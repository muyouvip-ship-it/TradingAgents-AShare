from __future__ import annotations

import argparse


def app() -> None:
    parser = argparse.ArgumentParser(prog="tradingagents")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("api", "scheduler"),
        default="api",
        help="Process to start.",
    )
    args = parser.parse_args()

    if args.command == "scheduler":
        from scheduler.main import main as scheduler_main

        scheduler_main()
        return

    from api.main import run as api_run

    api_run()
