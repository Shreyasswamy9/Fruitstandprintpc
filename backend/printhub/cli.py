"""Command-line administration: `printhub <command>`.

    printhub serve                     run the web service (used by systemd)
    printhub create-admin USERNAME     create an administrator (prompts for a password)
    printhub reset-password USERNAME   set a temporary password (prompts)
    printhub backup DEST_DIR           consistent copy of the database + settings
    printhub restore BACKUP_FILE       restore a database backup (service must be stopped)
    printhub cleanup                   run retention cleanup now
    printhub check                     print a health summary (exit 1 if CUPS/DB unhealthy)
"""
from __future__ import annotations

import argparse
import getpass
import json
import shutil
import sys
import time
from pathlib import Path

from .config import Config


def _state(config: Config):
    from .app import AppState

    config.background_tasks = False
    state = AppState(config)
    state.seed()
    return state


def _prompt_password() -> str:
    first = getpass.getpass("New password: ")
    if first != getpass.getpass("Repeat password: "):
        sys.exit("Passwords do not match.")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="printhub", description="Fruitstand Print Hub")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve")
    p = sub.add_parser("create-admin")
    p.add_argument("username")
    p.add_argument("--name", default="")
    p = sub.add_parser("reset-password")
    p.add_argument("username")
    p = sub.add_parser("backup")
    p.add_argument("dest", type=Path)
    p = sub.add_parser("restore")
    p.add_argument("backup", type=Path)
    p.add_argument("--yes", action="store_true")
    sub.add_parser("cleanup")
    sub.add_parser("check")
    args = parser.parse_args(argv)
    config = Config.from_env()

    if args.cmd == "serve":
        import uvicorn

        from .app import create_app

        uvicorn.run(create_app(config), host=config.host, port=config.port, proxy_headers=False,
                    access_log=False, log_level="warning")
        return 0

    if args.cmd == "restore":
        if not args.backup.is_file():
            sys.exit(f"No such backup file: {args.backup}")
        if not args.yes:
            sys.exit("Stop the service first (sudo systemctl stop printhub), then re-run with --yes.")
        if config.db_path.exists():
            keep = config.db_path.with_suffix(f".before-restore-{time.strftime('%Y%m%d-%H%M%S')}")
            shutil.copy2(config.db_path, keep)
            print(f"Previous database kept at {keep}")
        for suffix in ("-wal", "-shm"):
            Path(str(config.db_path) + suffix).unlink(missing_ok=True)
        shutil.copy2(args.backup, config.db_path)
        print("Restored. Start the service: sudo systemctl start printhub")
        return 0

    state = _state(config)
    if args.cmd == "create-admin":
        uid = state.accounts.create_user(args.username, args.name or args.username, _prompt_password(), "admin", must_change=False)
        state.events.record("admin", "user.created", "Administrator created from the command line", details={"new_user": f"user-{uid}"})
        print(f"Administrator {args.username} created.")
    elif args.cmd == "reset-password":
        row = state.db.one("SELECT id FROM users WHERE username = ?", (args.username,))
        if not row:
            sys.exit("No such user.")
        state.accounts.set_password(row["id"], _prompt_password(), must_change=True)
        state.db.execute("UPDATE users SET active = 1 WHERE id = ?", (row["id"],))
        print("Temporary password set; the user must change it at next sign-in.")
    elif args.cmd == "backup":
        args.dest.mkdir(parents=True, exist_ok=True)
        target = args.dest / f"printhub-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3"
        state.db.backup_to(target)
        print(target)
    elif args.cmd == "cleanup":
        print(json.dumps(state.run_cleanup(), indent=2))
    elif args.cmd == "check":
        state.registry.refresh_status(probe=True)
        health = state.diagnostics.health()
        for c in health["checks"]:
            mark = {True: "OK  ", False: "FAIL", None: "--  "}[c["ok"]]
            print(f"[{mark}] {c['name']}: {c['detail']}")
        for p in health["printers"]:
            print(f"       printer {p['name']}: {p['status']['label']}")
        return 0 if all(c["ok"] is not False for c in health["checks"][:3]) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
