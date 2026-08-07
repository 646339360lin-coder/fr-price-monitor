CREATE TABLE IF NOT EXISTS products (
  account_key TEXT NOT NULL,
  market TEXT NOT NULL,
  asin TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  metadata_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (account_key, market, asin)
);

CREATE INDEX IF NOT EXISTS idx_products_market_active
  ON products (account_key, market, active);

CREATE TABLE IF NOT EXISTS latest_prices (
  account_key TEXT NOT NULL,
  market TEXT NOT NULL,
  asin TEXT NOT NULL,
  scraped_at TEXT NOT NULL,
  status TEXT,
  current_price REAL,
  msrp_price REAL,
  record_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (account_key, market, asin)
);

CREATE INDEX IF NOT EXISTS idx_latest_prices_market_status
  ON latest_prices (account_key, market, status);

CREATE TABLE IF NOT EXISTS price_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_key TEXT NOT NULL,
  market TEXT NOT NULL,
  asin TEXT NOT NULL,
  scraped_at TEXT NOT NULL,
  current_price REAL,
  msrp_price REAL,
  promotion_status TEXT,
  status TEXT,
  record_json TEXT NOT NULL,
  UNIQUE (account_key, market, asin, scraped_at)
);

CREATE INDEX IF NOT EXISTS idx_price_history_market_time
  ON price_history (account_key, market, scraped_at);

CREATE INDEX IF NOT EXISTS idx_price_history_product_time
  ON price_history (account_key, market, asin, scraped_at);

CREATE TABLE IF NOT EXISTS market_runs (
  account_key TEXT NOT NULL,
  market TEXT NOT NULL,
  generated_at TEXT NOT NULL,
  total_count INTEGER NOT NULL,
  success_count INTEGER NOT NULL,
  stale_count INTEGER NOT NULL,
  PRIMARY KEY (account_key, market)
);

CREATE TABLE IF NOT EXISTS user_product_state (
  email TEXT NOT NULL,
  account_key TEXT NOT NULL,
  market TEXT NOT NULL,
  asin TEXT NOT NULL,
  memo TEXT,
  memo_updated_at TEXT,
  focused INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (email, account_key, market, asin)
);

CREATE TABLE IF NOT EXISTS shell_opportunity_state (
  email TEXT NOT NULL,
  account_key TEXT NOT NULL,
  market TEXT NOT NULL,
  phone_brand TEXT NOT NULL,
  model TEXT NOT NULL,
  single_shell INTEGER NOT NULL DEFAULT 0,
  three_in_one INTEGER NOT NULL DEFAULT 0,
  breakthrough INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (email, account_key, market, phone_brand, model)
);
