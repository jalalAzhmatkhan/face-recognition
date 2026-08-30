"""Small CLI for one-off admin/ops tasks that have no HTTP endpoint.

Usage (BE-03 bootstrap admin — see backend/README.md):

    uv run python -m app.cli create_admin --email admin@example.com --password 'S0meStrongPass!'

There is deliberately no public signup endpoint for staff accounts (they are
created by an existing ADMIN once BE-04's user-management API exists) — but
the very first ADMIN has to come from somewhere. This command is that
somewhere, for dev/staging bootstrap only. It requires a reachable
`DATABASE_URL` (real Postgres) — it is NOT exercised by the test suite, which
has no live database (see backend/tests/test_db_schema.py).
"""

import argparse
import getpass
import sys

from app.core.security import hash_password
from app.db.session import get_sessionmaker
from app.models.enums import StaffRole
from app.repositories.staff_accounts import StaffAccountRepository


def create_admin(email: str, password: str) -> int:
    session_factory = get_sessionmaker()
    with session_factory() as db:
        repo = StaffAccountRepository(db)
        existing = repo.get_by_email(email)
        if existing is not None:
            # Idempotent: re-running the bootstrap command for the same email
            # does not create a duplicate or clobber an existing account.
            print(f"staff_accounts: '{email}' already exists (id={existing.id}); no changes made.")
            return 0

        from app.models.staff_account import StaffAccount

        account = StaffAccount(
            email=email,
            role=StaffRole.ADMIN,
            password_hash=hash_password(password),
        )
        db.add(account)
        db.commit()
        print(f"Created ADMIN staff account: {email} (id={account.id})")
        return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_admin_parser = subparsers.add_parser(
        "create_admin", help="Bootstrap the first ADMIN staff account (dev/staging only)."
    )
    create_admin_parser.add_argument("--email", required=True)
    create_admin_parser.add_argument(
        "--password",
        required=False,
        help="If omitted, you will be prompted (avoids the plaintext password "
        "landing in shell history).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "create_admin":
        password = args.password or getpass.getpass("Password for new ADMIN account: ")
        if not password:
            print("Password must not be empty.", file=sys.stderr)
            return 1
        return create_admin(args.email, password)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
