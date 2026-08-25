# actualq

Read an [Actual Budget](https://actualbudget.org) export from the command line.

No server. No credentials. No dependencies. One file of standard-library Python.

```sh
$ actualq accounts
account       on budget  closed   balance  transactions  first       last
------------  ---------  ------  --------  ------------  ----------  ----------
Checking      yes                 4,182.03          593  2023-10-18  2026-08-18
Credit Card   yes                  -514.60          610  2023-10-24  2026-08-18
Savings       yes                12,000.00          184  2025-07-28  2026-07-31

$ actualq txns --since 2026-08 --category Grocery --json
[
  {
    "date": "2026-08-14",
    "account": "Checking",
    "payee": "Costco",
    "category": "Everyday / Grocery",
    "amount": -142.87,
    "amount_cents": -14287,
    ...
  }
]
```

## Why

Every other way to get at Actual data programmatically — the official
`@actual-app/cli`, `actualpy`, the community CLIs — needs a **running
actual-server** and its password. That is a lot of setup to answer "what did I
spend on groceries in July".

You already have the answer on disk. Actual's export (Settings → Export data) is
a zip holding an ordinary SQLite database. `actualq` reads it.

That makes it a good fit for LLM agents in particular: one binary-free command,
JSON out, nothing to authenticate, and no way to damage the budget.

## Install

```sh
uv tool install actualq        # or: pipx install actualq
```

Or just take the file. It has no dependencies and needs Python 3.11+:

```sh
curl -O https://raw.githubusercontent.com/madhurdeepjain/actualq/main/actualq.py
python3 actualq.py accounts
```

## Use

With no `-f`, it reads the newest `.zip` in the current directory, so the usual
session is `cd` to wherever you export and start asking.

```sh
actualq accounts                                  # balances, ranges, row counts
actualq txns --since 2026-01 --account Checking   # transactions
actualq categories --since 2026-07 --until 2026-07
actualq payees --limit 20
actualq sql "select ..."                          # anything else
actualq schema                                    # the field guide
```

`txns` filters: `--since` `--until` `--account` `--category` `--payee`
`--search` `--limit` `--uncategorized` `--no-transfers` `--splits`.

Dates take a year, a month or a day — `--since 2026`, `--since 2026-08`,
`--since 2026-08-22` — and `--until` means the **last** day of whatever you name.

Output is an aligned table by default, `--json` for an array, `--csv` for CSV.

## What it will not do

It does not write. There is no import, no edit, no sync. The export is copied to
a temp directory and opened read-only, so nothing here can reach the budget you
actually use, and `actualq sql "delete from ..."` fails rather than working.

It does not compute budget-vs-actual. The rollover arithmetic behind Actual's
budget screen is genuinely involved, and a number that is nearly right is worse
than no number in a tool you would use to check yourself. The raw
`zero_budgets` / `reflect_budgets` tables are there for `actualq sql`.

## The part worth reading: `actualq schema`

Actual's schema has four traps, and every one of them fails **quietly** — you get
plausible numbers that are wrong. This is most of why this tool exists.

**1. Read `v_transactions`, never `transactions`.** Payees and categories are
indirected through mapping tables (`payee_mapping.targetId`,
`category_mapping.transferId`). `transactions.description` holds a payee id that
may have been merged away, so joining `payees` directly returns NULL for every
payee you ever renamed or merged — and those rows read as having no payee at all.
Categories do the same and read as uncategorised.

**2. Splits are counted twice if you let them.** A split is a parent row carrying
the *full* amount plus children carrying the pieces. Both are real rows. Actual
computes balances over `is_parent = 0`. On a real file:

```
--splits leaves     5724 rows   matches the account balances   <- the default
--splits parents    5718 rows   matches them too, one row per bank transaction
--splits all        5728 rows   over by the whole value of every split
```

**3. Dates and amounts are integers.** `date` is `20260822`, an INTEGER, not a
string. `amount` is cents, negative for money out. `actualq` gives you both
`amount` (readable) and `amount_cents` (exact) so nothing has to round twice.

**4. Deleted rows are still in the file.** Nothing is deleted, it gets
`tombstone = 1`, because Actual syncs by CRDT and has to remember the deletion.
Query `accounts`, `categories` or `payees` yourself without `WHERE tombstone = 0`
and you report on things the user threw away.

`actualq schema` prints all of this, plus the tables worth knowing about, so an
agent can read it before writing SQL.

## Tests

```sh
python3 -m unittest discover
```

`schema.sql` is Actual's own schema, structure only, no data. The tests build a
synthetic budget from it containing one of each thing that is easy to get wrong,
and pin the behaviour above.

## Compatibility

Written against Actual's schema as of 2026. The views it depends on
(`v_transactions`, `v_payees`) are what the app itself reads, so they are the
most stable surface available — but this is not a documented API, and a future
migration could change it.

## License

MIT
