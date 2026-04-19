-- Phase 1: additive IPFS index columns for mesh_entries (Postgres)
ALTER TABLE mesh_entries ADD COLUMN IF NOT EXISTS ipfs_cid VARCHAR(128);
ALTER TABLE mesh_entries ADD COLUMN IF NOT EXISTS content_addressed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE mesh_entries ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMPTZ;
ALTER TABLE mesh_entries ADD COLUMN IF NOT EXISTS pin_count INTEGER NOT NULL DEFAULT 0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mesh_entries_ipfs_cid
  ON mesh_entries(ipfs_cid)
  WHERE ipfs_cid IS NOT NULL;
