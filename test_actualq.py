"""Tests for actualq, against a synthetic Actual file built from Actual's own schema.

schema.sql is structure only — no data of any kind — so these tests need nothing
but this repository.
"""

import contextlib
import io
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import actualq

HERE = Path(__file__).resolve().parent


def build(tmp: Path) -> Path:
    """An Actual file holding one of each thing that is easy to get wrong."""
    db = tmp / "db.sqlite"
    con = sqlite3.connect(db)
    con.executescript((HERE / "schema.sql").read_text())

    con.execute("insert into accounts (id,name,offbudget,closed,tombstone) values ('a1','Checking',0,0,0)")
    con.execute("insert into accounts (id,name,offbudget,closed,tombstone) values ('a2','Deleted',0,0,1)")
    con.execute("insert into category_groups (id,name,tombstone) values ('g1','Everyday',0)")
    con.execute("insert into categories (id,name,cat_group,tombstone) values ('c1','Grocery','g1',0)")
    con.execute("insert into category_mapping values ('c1','c1')")

    # Two payee ids, one merged into the other. `Costco Wholesale` was merged away, and
    # its mapping row is what still points its transactions at the survivor.
    con.execute("insert into payees (id,name,tombstone) values ('p1','Costco',0)")
    con.execute("insert into payee_mapping values ('p1','p1')")
    con.execute("insert into payee_mapping values ('p_old','p1')")

    def txn(tid, date, amount, *, acct="a1", desc="p1", cat="c1",
            parent=0, child=0, parent_id=None, tomb=0):
        con.execute(
            "insert into transactions "
            "(id,acct,description,category,amount,date,isParent,isChild,parent_id,tombstone) "
            "values (?,?,?,?,?,?,?,?,?,?)",
            (tid, acct, desc, cat, amount, date, parent, child, parent_id, tomb),
        )

    txn("t1", 20260822, -1234)                       # ordinary
    txn("t2", 20260701, -5000, desc="p_old")         # payee merged away
    txn("t3", 20260615, -9900, parent=1, cat=None)   # split parent, full amount
    txn("t3a", 20260615, -4000, child=1, parent_id="t3")
    txn("t3b", 20260615, -5900, child=1, parent_id="t3")
    txn("t4", 20260101, -777, tomb=1)                # deleted
    txn("t5", 20260101, -888, acct="a2")             # in a deleted account

    con.commit()
    con.close()

    export = tmp / "budget.zip"
    with zipfile.ZipFile(export, "w") as zf:
        zf.write(db, "db.sqlite")
        zf.writestr("metadata.json", '{"budgetName":"Test"}')
    return export


class Harness(unittest.TestCase):
    def run_cli(self, *argv):
        import json

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            actualq.main([*argv, "-f", str(self.export), "--json"])
        return json.loads(buf.getvalue())

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.export = build(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()


class TestTraps(Harness):
    def test_merged_payee_resolves_through_the_mapping_table(self):
        # The whole point. Joining `payees` on transactions.description directly gives
        # None here, and the row reads as having no payee at all.
        rows = self.run_cli("txns")
        merged = next(r for r in rows if r["amount_cents"] == -5000)
        self.assertEqual(merged["payee"], "Costco")

    def test_split_children_are_what_add_up(self):
        leaves = self.run_cli("txns", "--splits", "leaves")
        every = self.run_cli("txns", "--splits", "all")
        parents = self.run_cli("txns", "--splits", "parents")

        self.assertEqual(sum(r["amount_cents"] for r in leaves), -1234 - 5000 - 9900)
        self.assertEqual(sum(r["amount_cents"] for r in parents), -1234 - 5000 - 9900)
        # Counting both halves is the mistake, and it is worth pinning what it costs.
        self.assertEqual(sum(r["amount_cents"] for r in every), -1234 - 5000 - 9900 * 2)
        self.assertEqual(len(leaves), 4)
        self.assertEqual(len(every), 5)

    def test_split_parent_carries_no_category(self):
        parent = next(r for r in self.run_cli("txns", "--splits", "all")
                      if r["split"] == "parent")
        self.assertIsNone(parent["category"])

    def test_deleted_rows_and_deleted_accounts_are_left_out(self):
        amounts = {r["amount_cents"] for r in self.run_cli("txns", "--splits", "all")}
        self.assertNotIn(-777, amounts)   # tombstoned transaction
        self.assertNotIn(-888, amounts)   # transaction in a tombstoned account

    def test_balance_is_the_sum_of_the_leaves(self):
        checking = next(a for a in self.run_cli("accounts") if a["account"] == "Checking")
        self.assertEqual(checking["balance_cents"], -1234 - 5000 - 9900)
        self.assertEqual(checking["balance"], -161.34)

    def test_amounts_come_back_exact_as_well_as_readable(self):
        row = next(r for r in self.run_cli("txns") if r["amount_cents"] == -1234)
        self.assertEqual(row["amount"], -12.34)


class TestDates(unittest.TestCase):
    def test_integer_dates_become_iso(self):
        self.assertEqual(actualq.to_iso(20260822), "2026-08-22")
        self.assertIsNone(actualq.to_iso(None))

    def test_a_year_or_month_is_a_range_and_the_end_is_inclusive(self):
        self.assertEqual(actualq.from_iso("2026", end=False), 20260101)
        self.assertEqual(actualq.from_iso("2026", end=True), 20261231)
        self.assertEqual(actualq.from_iso("2026-08", end=False), 20260801)
        self.assertEqual(actualq.from_iso("2026-08", end=True), 20260831)
        self.assertEqual(actualq.from_iso("2026-02", end=True), 20260228)
        self.assertEqual(actualq.from_iso("2026-12", end=True), 20261231)
        self.assertEqual(actualq.from_iso("2026-08-22", end=True), 20260822)

    def test_a_month_bound_includes_its_last_day(self):
        # Off by one here silently drops the last month of any query that names one.
        self.assertGreaterEqual(actualq.from_iso("2026-08", end=True), 20260831)


class TestFiltering(Harness):
    def test_since_and_until_bound_by_month(self):
        rows = self.run_cli("txns", "--since", "2026-07", "--until", "2026-07")
        self.assertEqual([r["amount_cents"] for r in rows], [-5000])

    def test_uncategorized_ignores_split_parents(self):
        # The parent has no category by construction; reporting it as unfiled is noise.
        self.assertEqual(self.run_cli("txns", "--uncategorized"), [])


class TestSafety(unittest.TestCase):
    def test_the_source_file_is_never_opened_for_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = build(Path(tmp))
            before = export.stat().st_mtime_ns, export.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):
                actualq.main(["accounts", "-f", str(export), "--json"])
            self.assertEqual((export.stat().st_mtime_ns, export.read_bytes()), before)

    def test_sql_cannot_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = build(Path(tmp))
            with self.assertRaises(SystemExit) as e:
                actualq.main(["sql", "-f", str(export), "delete from transactions"])
            self.assertIn("readonly", str(e.exception).lower())


class TestCli(unittest.TestCase):
    def test_it_runs_as_a_script(self):
        out = subprocess.run(
            [sys.executable, str(HERE / "actualq.py"), "schema"],
            capture_output=True, text=True,
        )
        self.assertEqual(out.returncode, 0)
        self.assertIn("v_transactions", out.stdout)


if __name__ == "__main__":
    unittest.main()
