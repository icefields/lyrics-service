-- init_db.sql: Create table and indexes
CREATE TABLE IF NOT EXISTS lyrics (
  id BIGINT PRIMARY KEY,
  name TEXT,
  trackName TEXT,
  artistName TEXT,
  albumName TEXT,
  duration DOUBLE PRECISION,
  instrumental BOOLEAN,
  plainLyrics TEXT,
  syncedLyrics JSONB,
  fetched_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Expression index for case-insensitive trimmed lookups
CREATE UNIQUE INDEX IF NOT EXISTS uq_lyrics_artist_track_album ON lyrics (
  lower(trim(artistName)),
  lower(trim(trackName)),
  lower(coalesce(trim(albumName), ''))
);

CREATE INDEX IF NOT EXISTS idx_lyrics_synced_gin ON lyrics USING GIN (syncedLyrics jsonb_path_ops);

