#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""actualq — read an Actual Budget export and print clean rows.

No server, no credentials, no dependencies. Point it at the .zip you get from
Actual's Settings -> Export data and ask questions.

It never opens your file in place: the export is copied to a temp directory and
opened read-only, so nothing here can touch the budget you actually use.

Run `actualq schema` for what the tables mean and where the traps are.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

__version__ = "0.1.0"


# --- finding and opening the file ----------------------------------------


def find_source(given: str | None) -> Path:
    """The export to read: what you named, or the newest zip in the current directory."""
    if given:
        p = Path(given).expanduser()
        if not p.exists():
            raise SystemExit(f"actualq: {p} does not exist")
        if p.is_dir():
            # An Actual data directory holds db.sqlite directly; anything else, look
            # for the newest export in it.
            if (p / "db.sqlite").exists():
                return p / "db.sqlite"
            return _newest_zip(p)
        return p
    return _newest_zip(Path.cwd())


def _newest_zip(directory: Path) -> Path:
    zips = sorted(directory.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not zips:
        raise SystemExit(
            f"actualq: no .zip found in {directory}\n"
            "  Export one from Actual: Settings -> Export data,\n"
            "  or name one: actualq txns -f path/to/export.zip"
        )
    return zips[0]


def open_db(source: Path, tmp: Path) -> sqlite3.Connection:
    """Copy `source` into `tmp` and open it read-only.

    Always a copy. A live Actual database keeps recent writes in a -wal sidecar, so
    that is copied too when it is there — without it you would silently read a budget
    missing everything since the last checkpoint.
    """
    db = tmp / "db.sqlite"
    if source.suffix == ".zip":
        with zipfile.ZipFile(source) as zf:
            names = zf.namelist()
            if "db.sqlite" not in names:
                raise SystemExit(
                    f"actualq: {source.name} has no db.sqlite in it, so it is not an "
                    "Actual export"
                )
            db.write_bytes(zf.read("db.sqlite"))
    else:
        shutil.copy2(source, db)
        for side in ("-wal", "-shm"):
            extra = source.with_name(source.name + side)
            if extra.exists():
                shutil.copy2(extra, db.with_name(db.name + side))

    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        con.execute("select 1 from v_transactions limit 1")
    except sqlite3.DatabaseError as e:
        raise SystemExit(f"actualq: {source.name} is not readable as an Actual file ({e})")
    return con


# --- conversions ----------------------------------------------------------


def to_iso(yyyymmdd: int | None) -> str | None:
    """Actual stores dates as the integer 20260822. Give back 2026-08-22."""
    if not yyyymmdd:
        return None
    s = str(yyyymmdd)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def from_iso(text: str, *, end: bool) -> int:
    """A bound written as 2026, 2026-08 or 2026-08-22, as Actual's integer date.

    A year or a month is a range, so which end you want matters: --since 2026-08 is
    the 1st and --until 2026-08 is the 31st. Getting this wrong quietly drops the
    last month of every query that names one.
    """
    parts = text.strip().split("-")
    try:
        if len(parts) == 1:
            y = int(parts[0])
            return y * 10000 + (1231 if end else 101)
        if len(parts) == 2:
            y, m = int(parts[0]), int(parts[1])
            if not end:
                return y * 10000 + m * 100 + 1
            nxt = dt.date(y + (m == 12), 1 if m == 12 else m + 1, 1)
            last = nxt - dt.timedelta(days=1)
            return int(last.strftime("%Y%m%d"))
        return int(dt.date(int(parts[0]), int(parts[1]), int(parts[2])).strftime("%Y%m%d"))
    except (ValueError, IndexError):
        raise SystemExit(f"actualq: cannot read {text!r} as a date (try 2026, 2026-08, 2026-08-22)")


def dollars(cents: int | None) -> float:
    """Cents as a number of currency units, rounded once, here, and nowhere else."""
    return round((cents or 0) / 100, 2)


# --- queries --------------------------------------------------------------

# v_transactions is the view Actual itself reads, and using it is not optional: it
# resolves payees through payee_mapping and categories through category_mapping,
# drops tombstoned rows, and blanks the category on split parents. Query the raw
# `transactions` table instead and every renamed payee reads as NULL.
TXN_SQL = """
SELECT t.id,
       t.date,
       t.amount,
       t.notes,
       t.imported_payee,
       t.is_parent,
       t.is_child,
       t.parent_id,
       t.transfer_id,
       t.cleared,
       t.reconciled,
       t.starting_balance_flag,
       a.name    AS account,
       a.offbudget,
       p.name    AS payee,
       p.transfer_acct,
       c.name    AS category,
       g.name    AS category_group,
       c.is_income
FROM v_transactions t
LEFT JOIN accounts        a ON a.id = t.account
LEFT JOIN v_payees        p ON p.id = t.payee
LEFT JOIN categories      c ON c.id = t.category
LEFT JOIN category_groups g ON g.id = c.cat_group
WHERE t.account IS NOT NULL
"""


def txn_row(r: sqlite3.Row) -> dict:
    return {
        "date": to_iso(r["date"]),
        "account": r["account"],
        "payee": r["payee"],
        "category": (
            f"{r['category_group']} / {r['category']}" if r["category"] else None
        ),
        "amount": dollars(r["amount"]),
        "amount_cents": r["amount"] or 0,
        "notes": r["notes"],
        "imported_payee": r["imported_payee"],
        "transfer": bool(r["transfer_id"]) or bool(r["transfer_acct"]),
        "split": "parent" if r["is_parent"] else ("child" if r["is_child"] else None),
        "cleared": bool(r["cleared"]),
        "reconciled": bool(r["reconciled"]),
        "id": r["id"],
    }


def cmd_txns(con, args) -> list[dict]:
    sql, params = TXN_SQL, []

    # Splits are the trap in every naive total. The parent carries the full amount and
    # the children carry the same money again, so summing everything double-counts.
    # "leaves" is what adds up to the account balance, and is the default.
    if args.splits == "leaves":
        sql += " AND t.is_parent = 0"
    elif args.splits == "parents":
        sql += " AND t.is_child = 0"
    elif args.splits == "children":
        sql += " AND t.is_child = 1"

    if args.since:
        sql += " AND t.date >= ?"
        params.append(from_iso(args.since, end=False))
    if args.until:
        sql += " AND t.date <= ?"
        params.append(from_iso(args.until, end=True))
    if args.account:
        sql += " AND a.name LIKE ?"
        params.append(f"%{args.account}%")
    if args.category:
        sql += " AND (c.name LIKE ? OR g.name LIKE ?)"
        params += [f"%{args.category}%", f"%{args.category}%"]
    if args.payee:
        sql += " AND p.name LIKE ?"
        params.append(f"%{args.payee}%")
    if args.search:
        sql += " AND (t.notes LIKE ? OR p.name LIKE ? OR t.imported_payee LIKE ?)"
        params += [f"%{args.search}%"] * 3
    if args.uncategorized:
        sql += " AND t.category IS NULL AND t.is_parent = 0 AND t.transfer_id IS NULL"
    if args.no_transfers:
        sql += " AND t.transfer_id IS NULL AND p.transfer_acct IS NULL"

    sql += " ORDER BY t.date DESC, t.sort_order DESC"
    if args.limit:
        sql += f" LIMIT {int(args.limit)}"

    return [txn_row(r) for r in con.execute(sql, params)]


def cmd_accounts(con, args) -> list[dict]:
    # Balance excludes split parents for the same reason totals do.
    rows = con.execute(
        """
        SELECT a.name,
               a.offbudget,
               a.closed,
               COUNT(t.id)                              AS n,
               IFNULL(SUM(t.amount), 0)                 AS balance,
               MIN(t.date)                              AS first,
               MAX(t.date)                              AS last
        FROM accounts a
        LEFT JOIN v_transactions t ON t.account = a.id AND t.is_parent = 0
        WHERE a.tombstone = 0
        GROUP BY a.id
        ORDER BY a.closed, a.offbudget, a.name
        """
    )
    return [
        {
            "account": r["name"],
            "on_budget": not r["offbudget"],
            "closed": bool(r["closed"]),
            "balance": dollars(r["balance"]),
            "balance_cents": r["balance"],
            "transactions": r["n"],
            "first": to_iso(r["first"]),
            "last": to_iso(r["last"]),
        }
        for r in rows
    ]


def cmd_categories(con, args) -> list[dict]:
    where, params = "", []
    if args.since:
        where += " AND t.date >= ?"
        params.append(from_iso(args.since, end=False))
    if args.until:
        where += " AND t.date <= ?"
        params.append(from_iso(args.until, end=True))

    rows = con.execute(
        f"""
        SELECT g.name AS grp, c.name AS name, c.is_income, c.hidden,
               COUNT(t.id) AS n, IFNULL(SUM(t.amount), 0) AS total
        FROM categories c
        LEFT JOIN category_groups g ON g.id = c.cat_group
        LEFT JOIN v_transactions t ON t.category = c.id AND t.is_parent = 0 {where}
        WHERE c.tombstone = 0
        GROUP BY c.id
        ORDER BY g.name, c.name
        """,
        params,
    )
    return [
        {
            "category": f"{r['grp']} / {r['name']}",
            "group": r["grp"],
            "name": r["name"],
            "income": bool(r["is_income"]),
            "hidden": bool(r["hidden"]),
            "transactions": r["n"],
            "total": dollars(r["total"]),
            "total_cents": r["total"],
        }
        for r in rows
    ]


def cmd_payees(con, args) -> list[dict]:
    rows = con.execute(
        """
        SELECT p.name, p.transfer_acct,
               COUNT(t.id) AS n, IFNULL(SUM(t.amount), 0) AS total
        FROM v_payees p
        LEFT JOIN v_transactions t ON t.payee = p.id AND t.is_parent = 0
        WHERE p.tombstone = 0
        GROUP BY p.id
        HAVING n > 0
        ORDER BY n DESC, p.name
        """
    )
    out = [
        {
            "payee": r["name"],
            "transfer": bool(r["transfer_acct"]),
            "transactions": r["n"],
            "total": dollars(r["total"]),
            "total_cents": r["total"],
        }
        for r in rows
    ]
    return out[: args.limit] if args.limit else out


def cmd_sql(con, args) -> list[dict]:
    try:
        rows = con.execute(args.query).fetchall()
    except sqlite3.Error as e:
        raise SystemExit(f"actualq: {e}")
    return [dict(r) for r in rows]


# --- output ---------------------------------------------------------------


def emit(rows: list[dict], args) -> None:
    if args.json:
        json.dump(rows, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    elif args.csv:
        if not rows:
            return
        w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    else:
        table(rows)


# Wide, low-signal fields are kept out of the human table but stay in --json, where
# the exact integer is what a script should be doing arithmetic on anyway.
TABLE_SKIP = {"id", "amount_cents", "total_cents", "balance_cents", "imported_payee",
              "group", "name"}

# One bank descriptor 900 characters long otherwise sets the width of a column for
# every other row, and the table stops being readable at all. Only the human table
# truncates; --json and --csv always give you the whole value.
MAX_CELL = 44


def table(rows: list[dict]) -> None:
    if not rows:
        print("(nothing matched)")
        return
    cols = [c for c in rows[0] if c not in TABLE_SKIP]

    def cell(v) -> str:
        if v is None:
            return ""
        if isinstance(v, bool):
            return "yes" if v else ""
        if isinstance(v, float):
            return f"{v:,.2f}"
        return str(v)

    def clip(v: str) -> str:
        return v if len(v) <= MAX_CELL else v[: MAX_CELL - 1] + "\u2026"

    text = [[clip(cell(r.get(c))) for c in cols] for r in rows]
    width = [max(len(c), *(len(t[i]) for t in text)) for i, c in enumerate(cols)]
    numeric = [all(isinstance(r.get(c), (int, float)) and not isinstance(r.get(c), bool)
                   for r in rows) for c in cols]

    def line(vals):
        return "  ".join(
            v.rjust(width[i]) if numeric[i] else v.ljust(width[i])
            for i, v in enumerate(vals)
        ).rstrip()

    print(line([c.replace("_", " ") for c in cols]))
    print("  ".join("-" * w for w in width))
    for t in text:
        print(line(t))


# --- the field guide ------------------------------------------------------

SCHEMA_NOTES = """\
Actual's schema, and the four things that will bite you
=======================================================

An export .zip holds db.sqlite and metadata.json. It is an ordinary SQLite file,
so you can open it with anything. What follows is what is not obvious from the
table definitions.

1. Read v_transactions, never the transactions table
---------------------------------------------------
Payees and categories are indirected through mapping tables:

    payee_mapping.targetId       payees merged into one point at the survivor
    category_mapping.transferId  same for categories

`transactions.description` holds a payee id that may have been merged away, so a
direct join to `payees` returns NULL for every payee you ever renamed or merged,
and those rows read as having no payee. The same for categories: they read as
uncategorised. The view v_transactions does the mapping join for you, drops
tombstoned rows, and is what the app itself reads. Use it.

2. Split transactions are counted twice if you let them
-------------------------------------------------------
A split has a parent row carrying the full amount (is_parent = 1) and child rows
carrying the pieces (is_child = 1, parent_id set). Both are real rows. Actual
computes balances over is_parent = 0, so:

    leaves    is_parent = 0   adds up to the balance          <- the default here
    parents   is_child  = 0   one row per bank transaction
    children  is_child  = 1   the pieces only

The parent's category is forced to NULL by the view, so a split's categorisation
lives entirely in its children.

3. Dates are integers, amounts are integers
--------------------------------------------
date is YYYYMMDD as an INTEGER: 20260822, not a string, not a timestamp. It sorts
and compares correctly as a number, which is why it is stored that way.

amount is an INTEGER of cents, negative for money leaving. Never hold it as a
float. actualq gives you both `amount` (a rounded number, for reading) and
`amount_cents` (the exact integer, for arithmetic).

4. Deleted rows are still in the file
--------------------------------------
Nothing is deleted; it gets tombstone = 1, because Actual syncs by CRDT and needs
to remember the deletion. Every table has it. v_transactions filters it already,
but if you query accounts, categories or payees yourself, add
`WHERE tombstone = 0` or you will report on things the user threw away.

Rows in a deleted account are also still there, with account resolving to NULL.
actualq leaves them out.

Tables worth knowing
--------------------
    v_transactions      transactions, mapped and alive. Start here.
    v_payees            payees, with transfer payees showing the account name
    accounts            offbudget, closed, tombstone
    categories          cat_group -> category_groups.id, is_income, hidden
    zero_budgets        envelope budgets, month as YYYYMM integer
    reflect_budgets     tracking budgets, same shape
    rules / schedules   conditions and actions as JSON strings
    custom_reports      Reports tab, undocumented and version-specific

`actualq sql "..."` runs anything you like against a read-only copy.
"""


# --- cli ------------------------------------------------------------------

COMMANDS = {
    "txns": cmd_txns,
    "accounts": cmd_accounts,
    "categories": cmd_categories,
    "payees": cmd_payees,
    "sql": cmd_sql,
}


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-f", "--file", help="export .zip (default: the newest one in this directory)")
    common.add_argument("--json", action="store_true", help="JSON array on stdout")
    common.add_argument("--csv", action="store_true", help="CSV on stdout")

    dated = argparse.ArgumentParser(add_help=False)
    dated.add_argument("--since", metavar="DATE", help="2026, 2026-08 or 2026-08-22")
    dated.add_argument("--until", metavar="DATE", help="inclusive; a year or month means its last day")

    p = argparse.ArgumentParser(
        prog="actualq",
        description="Read an Actual Budget export. No server, no dependencies.",
    )
    p.add_argument("--version", action="version", version=f"actualq {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("txns", parents=[common, dated], help="transactions")
    t.add_argument("--account", help="substring match")
    t.add_argument("--category", help="substring match on category or group")
    t.add_argument("--payee", help="substring match")
    t.add_argument("--search", help="substring of notes, payee or the bank's own wording")
    t.add_argument("--limit", type=int)
    t.add_argument("--splits", choices=["leaves", "parents", "children", "all"],
                   default="leaves", help="default leaves: what adds up to the balance")
    t.add_argument("--uncategorized", action="store_true", help="rows with no category")
    t.add_argument("--no-transfers", action="store_true", help="drop movements between own accounts")

    sub.add_parser("accounts", parents=[common], help="accounts and balances")
    sub.add_parser("categories", parents=[common, dated], help="categories and totals")

    y = sub.add_parser("payees", parents=[common], help="payees by frequency")
    y.add_argument("--limit", type=int)

    s = sub.add_parser("sql", parents=[common], help="arbitrary read-only SQL")
    s.add_argument("query", help="the statement to run")

    sub.add_parser("schema", help="what the tables mean and where the traps are")
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except BrokenPipeError:
        # `actualq txns | head`. Catching it is not enough: Python flushes stdout
        # again on the way out, the pipe is still gone, and it prints a warning over
        # whatever you piped into. Point the fd at devnull so the last flush lands
        # somewhere. This is the documented workaround.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except KeyboardInterrupt:
        return 130


def _run(argv: list[str] | None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "schema":
        print(SCHEMA_NOTES)
        return 0

    source = find_source(args.file)
    with tempfile.TemporaryDirectory(prefix="actualq-") as tmp:
        con = open_db(source, Path(tmp))
        try:
            emit(COMMANDS[args.cmd](con, args), args)
        finally:
            con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
