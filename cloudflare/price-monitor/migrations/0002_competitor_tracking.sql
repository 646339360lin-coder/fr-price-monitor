CREATE TABLE IF NOT EXISTS competitor_products (
  account_key TEXT NOT NULL,
  market TEXT NOT NULL,
  asin TEXT NOT NULL,
  benchmark_type TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (account_key, market, asin)
);

CREATE INDEX IF NOT EXISTS idx_competitor_products_market_active
  ON competitor_products (account_key, market, active, benchmark_type);

CREATE TABLE IF NOT EXISTS competitor_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_key TEXT NOT NULL,
  market TEXT NOT NULL,
  asin TEXT NOT NULL,
  scraped_at TEXT NOT NULL,
  status TEXT,
  current_price REAL,
  msrp_price REAL,
  record_json TEXT NOT NULL,
  screenshot_key TEXT,
  screenshot_content_type TEXT,
  created_at TEXT NOT NULL,
  UNIQUE (account_key, market, asin, scraped_at)
);

CREATE INDEX IF NOT EXISTS idx_competitor_snapshots_latest
  ON competitor_snapshots (account_key, market, asin, scraped_at DESC);

CREATE INDEX IF NOT EXISTS idx_competitor_snapshots_retention
  ON competitor_snapshots (account_key, market, scraped_at);
