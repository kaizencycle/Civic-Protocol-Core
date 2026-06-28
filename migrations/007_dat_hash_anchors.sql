-- C-357: Reserve Block .dat hash anchors (NDJSON cold canon path)
-- CPC stores hash proofs only — full block data lives in GitHub (Mobius-Substrate).

CREATE TABLE IF NOT EXISTS dat_hash_anchors (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  dat_file            TEXT NOT NULL UNIQUE,
  file_hash           TEXT NOT NULL,
  block_range_start   INTEGER NOT NULL,
  block_range_end     INTEGER NOT NULL,
  block_count         INTEGER NOT NULL,
  chain_tip_hash      TEXT NOT NULL,
  manifest_hash       TEXT,
  version             TEXT NOT NULL DEFAULT '1.0',
  canonized_at        TEXT NOT NULL,
  created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_dat_anchors_range
  ON dat_hash_anchors(block_range_start, block_range_end);

CREATE INDEX IF NOT EXISTS idx_dat_anchors_range_end
  ON dat_hash_anchors(block_range_end);
