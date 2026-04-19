-- C-286: OAA sovereign memory proofs (durable seal rows)
CREATE TABLE IF NOT EXISTS oaa_memory_proofs (
  hash              TEXT PRIMARY KEY,
  payload_type      TEXT NOT NULL,
  agent             TEXT NOT NULL,
  cycle             TEXT NOT NULL,
  key               TEXT NOT NULL,
  intent            TEXT,
  previous_hash     TEXT,
  timestamp         TIMESTAMPTZ NOT NULL,
  source            TEXT NOT NULL DEFAULT 'oaa-api-library',
  raw               JSONB NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oaa_memory_agent ON oaa_memory_proofs(agent);
CREATE INDEX IF NOT EXISTS idx_oaa_memory_key ON oaa_memory_proofs(key);
CREATE INDEX IF NOT EXISTS idx_oaa_memory_created ON oaa_memory_proofs(created_at DESC);
