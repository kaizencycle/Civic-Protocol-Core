-- C-286: MNS mesh entries table (Postgres-compatible; SQLite uses same DDL where supported)
CREATE TABLE IF NOT EXISTS mesh_entries (
  id              TEXT PRIMARY KEY,
  node_id         TEXT NOT NULL,
  node_tier       TEXT NOT NULL DEFAULT 'observer',
  timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  title           TEXT,
  sha             TEXT,
  source          TEXT NOT NULL DEFAULT 'mesh-node',
  raw             JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_mesh_entries_node_id ON mesh_entries(node_id);
CREATE INDEX IF NOT EXISTS idx_mesh_entries_timestamp ON mesh_entries(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_mesh_entries_node_tier ON mesh_entries(node_tier);
