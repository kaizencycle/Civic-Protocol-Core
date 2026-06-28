-- C-357: Reserve Block .dat hash anchors (NDJSON cold canon path)
-- CPC stores hash proofs only — full block data lives in GitHub (Mobius-Substrate).
-- Postgres-compatible (CI migration-check); SQLite ledger uses db.py bootstrap DDL.

CREATE TABLE IF NOT EXISTS dat_hash_anchors (
  id                  SERIAL PRIMARY KEY,
  dat_file            VARCHAR(32) NOT NULL UNIQUE,
  file_hash           VARCHAR(80) NOT NULL,
  block_range_start   INTEGER NOT NULL,
  block_range_end     INTEGER NOT NULL,
  block_count         INTEGER NOT NULL,
  chain_tip_hash      VARCHAR(80) NOT NULL,
  manifest_hash       VARCHAR(80),
  version             VARCHAR(10) NOT NULL DEFAULT '1.0',
  canonized_at        TIMESTAMPTZ NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dat_anchors_range
  ON dat_hash_anchors(block_range_start, block_range_end);

CREATE INDEX IF NOT EXISTS idx_dat_anchors_range_end
  ON dat_hash_anchors(block_range_end);
