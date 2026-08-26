---
name: actualq
description: Read an Actual Budget file to answer questions about spending, balances, transactions, categories and payees. Use whenever the user asks what they spent, what a balance is, where money went, or names an Actual Budget export or budget .zip.
---

# actualq

`actualq` reads an Actual Budget export — the `.zip` from Actual's
Settings → Export data, holding an ordinary SQLite database. No server, no
credentials, read-only. Answer budget questions with it rather than by opening
the SQLite file yourself: the schema has four traps that fail *quietly*, and
this tool has them handled and pinned by tests.

## Running it

```sh
uvx actualq accounts        # no install needed
actualq accounts            # if the user has it installed
```

With no `-f` it reads the newest `.zip` in the current directory. Otherwise
`-f PATH` takes an export, a directory of exports, or Actual's own data
directory (the one holding `db.sqlite`). If you cannot find an export, ask the
user where it is rather than guessing; do not try to reach an actual-server.

Add `--json` for machine-readable output. `amount_cents` / `total_cents` /
`balance_cents` are exact integers — do arithmetic on those, never on the
rounded `amount`.

## Pick the command

| the question | the command |
| --- | --- |
| balances, what accounts exist, date coverage | `actualq accounts` |
| what did I spend on X / show me transactions | `actualq txns --since 2026-07 --category grocery` |
| where did the money go last month | `actualq categories --since 2026-07 --until 2026-07` |
| who do I pay most | `actualq payees --limit 20` |
| anything else | `actualq sql "select ..."` |

`txns` filters: `--since --until --account --category --payee --search --limit
--uncategorized --no-transfers --splits`. Name matches are substrings, so
`--account cred` finds "Credit Card".

Dates take a year, a month or a day. `--until` means the **last** day of what
you name, so one whole month is `--since 2026-07 --until 2026-07`.

For real spending, exclude money the user moved between their own accounts:
`--no-transfers`.

## Before writing SQL, run `actualq schema`

It prints the field guide. The short version — every one of these produces
plausible wrong numbers rather than an error:

1. **Query `v_transactions`, never `transactions`.** Payees and categories are
   indirected through `payee_mapping` / `category_mapping`. Joining `payees`
   directly on `transactions.description` returns NULL for every payee the user
   ever renamed or merged, and those rows read as having no payee.
2. **Splits double-count.** A split is a parent row with the full amount plus
   children with the pieces; both are real rows. Filter `is_parent = 0` for
   totals — that is what adds up to the balance. A split parent's category is
   always NULL; the categorisation lives in its children.
3. **Dates and amounts are integers.** `date` is `20260822`, not a string.
   `amount` is cents, negative for money out.
4. **Deleted rows are still there** with `tombstone = 1`. `v_transactions`
   filters them; `accounts`, `categories` and `payees` do not — add
   `WHERE tombstone = 0` yourself.

Useful shape for a monthly rollup: `t.date/100 as month` gives `202608`.

## Limits worth stating rather than working around

- It is **read-only** by design. There is no write, import, or edit path. If
  the user wants to change their budget, they do that in Actual.
- It does **not** compute budget-vs-actual — Actual's rollover arithmetic is
  involved and a nearly-right number is worse than none. The raw
  `zero_budgets` / `reflect_budgets` tables are available to `actualq sql`
  (month is a `YYYYMM` integer) if the user asks for the raw figures.
- An export is a snapshot. If numbers look stale, the user needs a fresh
  export — say so rather than reconciling around it.
