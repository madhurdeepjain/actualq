-- Actual Budget's own schema, structure only — no data of any kind.
-- Dumped from an export so tests can build an empty file to work on.
-- Regenerate with: python3 tests/dump_schema.py

CREATE TABLE __meta__ (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE __migrations__ (id INT PRIMARY KEY NOT NULL);
CREATE TABLE accounts
   (id TEXT PRIMARY KEY,
    account_id TEXT,
    name TEXT,
    balance_current INTEGER,
    balance_available INTEGER,
    balance_limit INTEGER,
    mask TEXT,
    official_name TEXT,
    subtype TEXT,
    bank TEXT,
    offbudget INTEGER DEFAULT 0,
    closed INTEGER DEFAULT 0,
    tombstone INTEGER DEFAULT 0, sort_order REAL, type TEXT, account_sync_source TEXT, last_sync text, last_reconciled text, bank_sync_status text);
CREATE TABLE banks
 (id TEXT PRIMARY KEY,
  bank_id TEXT,
  name TEXT,
  tombstone INTEGER DEFAULT 0);
CREATE TABLE categories
 (id TEXT PRIMARY KEY,
  name TEXT,
  is_income INTEGER DEFAULT 0,
  cat_group TEXT,
  sort_order REAL,
  tombstone INTEGER DEFAULT 0, hidden BOOLEAN NOT NULL DEFAULT 0, goal_def TEXT DEFAULT null, template_settings JSON DEFAULT '{"source": "notes"}', cleanup_def TEXT DEFAULT NULL);
CREATE TABLE category_groups
   (id TEXT PRIMARY KEY,
    name TEXT,
    is_income INTEGER DEFAULT 0,
    sort_order REAL,
    tombstone INTEGER DEFAULT 0, hidden BOOLEAN NOT NULL DEFAULT 0);
CREATE TABLE category_mapping
  (id TEXT PRIMARY KEY,
   transferId TEXT);
CREATE TABLE cleanup_groups
  (id TEXT PRIMARY KEY,
   name TEXT NOT NULL,
   tombstone INTEGER DEFAULT 0);
CREATE TABLE created_budgets (month TEXT PRIMARY KEY);
CREATE TABLE custom_reports
  (
    id TEXT PRIMARY KEY,
    name TEXT,
    start_date TEXT,
    end_date TEXT,
    date_static INTEGER DEFAULT 0,
    date_range TEXT,
    mode TEXT DEFAULT 'total',
    group_by TEXT DEFAULT 'Category',
    balance_type TEXT DEFAULT 'Expense',
    show_empty INTEGER DEFAULT 0,
    show_offbudget INTEGER DEFAULT 0,
    show_hidden INTEGER DEFAULT 0,
    show_uncategorized INTEGER DEFAULT 0,
    selected_categories TEXT,
    graph_type TEXT DEFAULT 'BarGraph',
    conditions TEXT,
    conditions_op TEXT DEFAULT 'and',
    metadata TEXT,
    interval TEXT DEFAULT 'Monthly',
    color_scheme TEXT,
    tombstone INTEGER DEFAULT 0
  , include_current INTEGER DEFAULT 0, sort_by TEXT DEFAULT 'desc', trim_intervals INTEGER DEFAULT 0, show_trend_lines INTEGER DEFAULT 0);
CREATE TABLE dashboard
        (id TEXT PRIMARY KEY,
         type TEXT,
         width INTEGER,
         height INTEGER,
         x INTEGER,
         y INTEGER,
         meta TEXT,
         tombstone INTEGER DEFAULT 0, dashboard_page_id TEXT);
CREATE TABLE dashboard_pages
        (id TEXT PRIMARY KEY,
         name TEXT,
         tombstone INTEGER DEFAULT 0);
CREATE TABLE kvcache (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE kvcache_key (id INTEGER PRIMARY KEY, key REAL);
CREATE TABLE messages_clock (id INTEGER PRIMARY KEY, clock TEXT);
CREATE TABLE messages_crdt
 (id INTEGER PRIMARY KEY,
  timestamp TEXT NOT NULL UNIQUE,
  dataset TEXT NOT NULL,
  row TEXT NOT NULL,
  column TEXT NOT NULL,
  value BLOB NOT NULL);
CREATE TABLE notes
  (id TEXT PRIMARY KEY,
   note TEXT);
CREATE TABLE payee_locations (
      id TEXT PRIMARY KEY,
      payee_id TEXT,
      latitude REAL,
      longitude REAL,
      created_at INTEGER,
      tombstone INTEGER DEFAULT 0
    );
CREATE TABLE payee_mapping
  (id TEXT PRIMARY KEY,
   targetId TEXT);
CREATE TABLE payees
  (id TEXT PRIMARY KEY,
   name TEXT,
   category TEXT,
   tombstone INTEGER DEFAULT 0,
   transfer_acct TEXT, favorite INTEGER DEFAULT 0 DEFAULT FALSE, learn_categories BOOLEAN DEFAULT 1);
CREATE TABLE pending_transactions
  (id TEXT PRIMARY KEY,
   acct INTEGER,
   amount INTEGER,
   description TEXT,
   date TEXT,
   FOREIGN KEY(acct) REFERENCES accounts(id));
CREATE TABLE preferences
       (id TEXT PRIMARY KEY,
        value TEXT);
CREATE TABLE reflect_budgets
  (id TEXT PRIMARY KEY,
   month INTEGER,
   category TEXT,
   amount INTEGER DEFAULT 0,
   carryover INTEGER DEFAULT 0, goal INTEGER DEFAULT null, long_goal INTEGER DEFAULT null);
CREATE TABLE rules
  (id TEXT PRIMARY KEY,
   stage TEXT,
   conditions TEXT,
   actions TEXT,
   tombstone INTEGER DEFAULT 0, conditions_op TEXT DEFAULT 'and');
CREATE TABLE schedules
  (id TEXT PRIMARY KEY,
   rule TEXT,
   active INTEGER DEFAULT 0,
   completed INTEGER DEFAULT 0,
   posts_transaction INTEGER DEFAULT 0,
   tombstone INTEGER DEFAULT 0, name TEXT DEFAULT NULL, custom_upcoming_length TEXT DEFAULT NULL);
CREATE TABLE schedules_json_paths
  (schedule_id TEXT PRIMARY KEY,
   payee TEXT,
   account TEXT,
   amount TEXT,
   date TEXT);
CREATE TABLE schedules_next_date
  (id TEXT PRIMARY KEY,
   schedule_id TEXT,
   local_next_date INTEGER,
   local_next_date_ts INTEGER,
   base_next_date INTEGER,
   base_next_date_ts INTEGER, tombstone INTEGER DEFAULT 0);
CREATE TABLE tags(
  id TEXT PRIMARY KEY,
  tag TEXT UNIQUE,
  color TEXT,
  description TEXT
, tombstone integer DEFAULT 0, hidden BOOLEAN DEFAULT 0);
CREATE TABLE transaction_filters
  (id TEXT PRIMARY KEY,
   name TEXT,
   conditions TEXT,
   conditions_op TEXT DEFAULT 'and',
   tombstone INTEGER DEFAULT 0);
CREATE TABLE transactions
  (id TEXT PRIMARY KEY,
   isParent INTEGER DEFAULT 0,
   isChild INTEGER DEFAULT 0,
   acct TEXT,
   category TEXT,
   amount INTEGER,
   description TEXT,
   notes TEXT,
   date INTEGER,
   financial_id TEXT,
   type TEXT,
   location TEXT,
   error TEXT,
   imported_description TEXT,
   starting_balance_flag INTEGER DEFAULT 0,
   transferred_id TEXT,
   sort_order REAL,
   tombstone INTEGER DEFAULT 0, cleared INTEGER DEFAULT 1, pending INTEGER DEFAULT 0, parent_id TEXT, schedule TEXT, reconciled INTEGER DEFAULT 0, raw_synced_data text);
CREATE TABLE zero_budget_months
  (id TEXT PRIMARY KEY,
   buffered INTEGER DEFAULT 0);
CREATE TABLE zero_budgets
  (id TEXT PRIMARY KEY,
   month INTEGER,
   category TEXT,
   amount INTEGER DEFAULT 0,
   carryover INTEGER DEFAULT 0, goal INTEGER DEFAULT null, long_goal INTEGER DEFAULT null);
CREATE INDEX idx_payee_locations_geo_tombstone ON payee_locations (tombstone, latitude, longitude);
CREATE INDEX idx_payee_locations_payee_id ON payee_locations (payee_id);
CREATE INDEX idx_payee_locations_tombstone_payee_created ON payee_locations (tombstone, payee_id, created_at);
CREATE INDEX idx_transactions_acct_tombstone ON transactions(acct, tombstone);
CREATE INDEX idx_transactions_schedule ON transactions(schedule);
CREATE INDEX messages_crdt_search ON messages_crdt(dataset, row, column, timestamp);
CREATE INDEX trans_category ON transactions(category);
CREATE INDEX trans_category_date ON transactions(category, date);
CREATE INDEX trans_date ON transactions(date);
CREATE INDEX trans_parent_id ON transactions(parent_id);
CREATE INDEX trans_sorted ON transactions(date desc, starting_balance_flag, sort_order desc, id);
CREATE VIEW v_categories AS SELECT _.id, _.name, _.is_income, _.hidden, _.cat_group AS "group", _.goal_def, _.cleanup_def, _.template_settings, _.sort_order, _.tombstone FROM categories _;
CREATE VIEW v_payees AS SELECT _.id, COALESCE(__accounts.name, _.name) AS name, _.transfer_acct, _.tombstone, _.favorite, _.learn_categories FROM payees _
          LEFT JOIN accounts __accounts ON (_.transfer_acct = __accounts.id AND __accounts.tombstone = 0)
          -- We never want to show transfer payees that are pointing to deleted accounts.
          -- Either this is not a transfer payee, if the account exists
          WHERE _.transfer_acct IS NULL OR __accounts.id IS NOT NULL;
CREATE VIEW v_schedules AS SELECT _.id, _.name, _.rule, 
            CASE
              WHEN _nd.local_next_date_ts = _nd.base_next_date_ts THEN _nd.local_next_date
              ELSE _nd.base_next_date
            END
           AS next_date, _.completed, _.posts_transaction, _.custom_upcoming_length, _.tombstone, pm.targetId AS _payee, json_extract(_rules.conditions, _paths.account || '.value') AS _account, json_extract(_rules.conditions, _paths.amount || '.value') AS _amount, json_extract(_rules.conditions, _paths.amount || '.op') AS _amountOp, json_extract(_rules.conditions, _paths.date || '.value') AS _date, _rules.conditions AS _conditions, _rules.actions AS _actions FROM schedules _
        LEFT JOIN schedules_next_date _nd ON _nd.schedule_id = _.id
        LEFT JOIN schedules_json_paths _paths ON _paths.schedule_id = _.id
        LEFT JOIN rules _rules ON _rules.id = _.rule
        LEFT JOIN payee_mapping pm ON pm.id = json_extract(_rules.conditions, _paths.payee || '.value');
CREATE VIEW v_transactions AS SELECT _.id, _.is_parent, _.is_child, _.parent_id, a.id AS account, c.id AS category, _.amount, p.id AS payee, _.notes, _.date, _.imported_id, _.error, _.imported_payee, _.starting_balance_flag, _.transfer_id, _.sort_order, _.cleared, _.reconciled, _.tombstone, _.schedule, _.raw_synced_data FROM v_transactions_internal_alive _
          LEFT JOIN payees p ON (p.id = _.payee AND p.tombstone = 0)
          LEFT JOIN categories c ON (c.id = _.category AND c.tombstone = 0)
          LEFT JOIN accounts a ON (a.id = _.account AND a.tombstone = 0)
          ORDER BY _.date desc, _.starting_balance_flag, _.sort_order desc, _.id;
CREATE VIEW v_transactions_internal AS SELECT _.id, _.isParent AS is_parent, _.isChild AS is_child, CASE WHEN _.isChild = 0 THEN NULL ELSE _.parent_id END AS parent_id, _.acct AS account, CASE WHEN _.isParent = 1 THEN NULL ELSE cm.transferId END AS category, IFNULL(_.amount, 0) AS amount, pm.targetId AS payee, _.notes, _.date, _.financial_id AS imported_id, _.error, _.imported_description AS imported_payee, _.starting_balance_flag, _.transferred_id AS transfer_id, _.sort_order, _.cleared, _.reconciled, _.tombstone, _.schedule, _.raw_synced_data FROM transactions _
          LEFT JOIN category_mapping cm ON cm.id = _.category
          LEFT JOIN payee_mapping pm ON pm.id = _.description
          WHERE
           _.date IS NOT NULL AND
           _.acct IS NOT NULL AND
           (_.isChild = 0 OR _.parent_id IS NOT NULL);
CREATE VIEW v_transactions_internal_alive AS SELECT _.* FROM v_transactions_internal _
        LEFT JOIN transactions t2 ON (_.is_child = 1 AND t2.id = _.parent_id)
        WHERE IFNULL(_.tombstone, 0) = 0 AND (_.is_child = 0 OR t2.tombstone = 0);
