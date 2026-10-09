"""Command-line administration.

Create the admin account, or change its password::

    python -m backend.manage set-admin-password
    python -m backend.manage set-admin-password --username alice

The password is read from the terminal without echo. For scripted setups it
can instead be piped on stdin with ``--password-stdin``.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from backend.app.db.session import init_database, session_scope
from backend.app.services.accounts import AccountError, set_admin_password


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\r\n")
    first = getpass.getpass("New admin password: ")
    second = getpass.getpass("Repeat it: ")
    if first != second:
        raise AccountError("the passwords do not match")
    return first


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.manage")
    commands = parser.add_subparsers(dest="command", required=True)
    set_password = commands.add_parser(
        "set-admin-password", help="create the admin account or change its password"
    )
    set_password.add_argument("--username", default="admin")
    set_password.add_argument("--password-stdin", action="store_true")
    args = parser.parse_args(argv)

    init_database()
    try:
        password = _read_password(args.password_stdin)
        with session_scope() as session:
            set_admin_password(session, args.username, password)
    except AccountError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"admin account {args.username!r} saved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
