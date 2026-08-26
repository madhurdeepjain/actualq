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
uv tool install actualq     # or: pipx install actualq
```

Or run it once without installing anything:

```sh
uvx actualq accounts
```

Or take the file. It has no dependencies and needs only Python 3.11+, so there
is nothing to install if you would rather not:

```sh
curl -O https://raw.githubusercontent.com/madhurdeepjain/actualq/main/actualq.py
python3 actualq.py accounts
```

## Use

An export is a zip. In Actual: **Settings → Export data**. That is the whole
setup — nothing to run, no password, no sync id.

### Pointing it at a file

With no `-f`, `actualq` reads the newest `.zip` in the current directory, so the
usual session is `cd` to wherever your browser drops exports and start asking:

```sh
cd ~/Downloads
actualq accounts
```

`-f` takes a file or a directory:

```sh
actualq txns -f ~/budgets/2026-08-25-My-Finances.zip   # that export
actualq txns -f ~/budgets/                             # newest export in there
actualq txns -f ~/Documents/Actual/My-Finances-a1b2c3/ # a live data directory
```

The last form reads the folder Actual itself keeps `db.sqlite` in, if you would
rather not export at all. It is still a copy — the database and its `-wal`
sidecar are copied to a temp directory and opened read-only, so a running Actual
is neither disturbed nor half-read.

### The commands

```sh
actualq accounts    # balances, date ranges, row counts, one line per account
actualq txns        # transactions, newest first
actualq categories  # every category with its total and count
actualq payees      # payees by how often they appear
actualq sql "..."   # anything the above will not answer
actualq schema      # what the tables mean and where the traps are
```

`txns` and `categories` take `--since` / `--until`. `txns` also takes:

| filter | what it does |
| --- | --- |
| `--account NAME` | substring, case-insensitive: `--account cred` |
| `--category NAME` | substring of the category **or** its group |
| `--payee NAME` | substring |
| `--search TEXT` | notes, payee, or the bank's own wording (`imported_payee`) |
| `--limit N` | first N rows |
| `--uncategorized` | rows with no category, ignoring split parents and transfers |
| `--no-transfers` | drop movements between your own accounts |
| `--splits MODE` | `leaves` (default), `parents`, `children`, `all` — see below |

Dates take a year, a month or a day — `--since 2026`, `--since 2026-08`,
`--since 2026-08-22` — and `--until` means the **last** day of whatever you
name, so `--since 2026-07 --until 2026-07` is exactly July.

Output is an aligned table by default, `--json` for an array, `--csv` for CSV.
The table drops the wide, low-signal columns (`id`, `imported_payee`) and clips
long cells so one 900-character bank descriptor cannot set a column's width;
`--json` and `--csv` always carry every field, whole. They also carry the exact
integers — `amount_cents`, `total_cents`, `balance_cents` — which is what a
script should do arithmetic on, so nothing rounds twice.

### Recipes

```sh
# What did groceries cost in July?
actualq categories --since 2026-07 --until 2026-07

# Everything at one payee this year
actualq txns --since 2026 --payee costco

# Real spending: no transfers between my own accounts, credit card only
actualq txns --since 2026-08 --account "credit" --no-transfers

# Rows I never filed
actualq txns --uncategorized

# Find that charge I half-remember
actualq txns --search "annual fee"

# The pieces of a split, rather than the bank's single line
actualq txns --since 2026-08 --splits children

# Hand a month to a spreadsheet
actualq txns --since 2026-07 --until 2026-07 --csv > july.csv

# Total a filtered set exactly, in cents
actualq txns --since 2026-08 --category grocery --json \
  | jq '[.[].amount_cents] | add / 100'
```

`actualq txns | head` is fine; a closed pipe exits cleanly rather than printing a
traceback over what you piped into.

### `actualq sql`

Everything above is convenience over one read-only SQLite connection. When the
question does not fit a flag, write the query:

```sh
# Net by month, on-budget accounts only
actualq sql "
  select t.date/100 as month, sum(t.amount)/100.0 as net
  from v_transactions t
  join accounts a on a.id = t.account
  where t.is_parent = 0 and a.offbudget = 0
  group by month order by month"
```

```
 month       net
------  --------
202601  2,708.37
202602  2,705.47
202603  2,819.82
...
```

```sh
# Spending by category by month, income excluded
actualq sql "
  select t.date/100 as month,
         g.name || ' / ' || c.name as category,
         sum(-t.amount)/100.0 as spent
  from v_transactions t
  join categories c        on c.id = t.category
  join category_groups g   on g.id = c.cat_group
  where t.is_parent = 0 and c.is_income = 0 and t.date >= 20260101
  group by month, category
  order by month, spent desc"
```

Two things to keep in mind here. `sql` prints what the database holds, so dates
come back as `20260102` and amounts as cents unless you convert them yourself —
the other commands do that for you. And writes fail: the connection is opened
`mode=ro`, so `delete from transactions` is an error, not a lost budget.

### With an agent

In Claude Code:

```sh
/plugin marketplace add madhurdeepjain/actualq
/plugin install actualq@actualq
```

For Codex or anything else that reads `SKILL.md`, drop `skills/actualq/` into
`~/.agents/skills/`.

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
