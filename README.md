# Lyrics Service (Postgres-backed, lrclib fallback)

## What this project does

This service exposes a single endpoint:

`GET /getlyrics?artist_name=<artist>&track_name=<track>&album_name=<album_optional>`

Behavior:
1. Query the PostgreSQL `lyrics` table (the database is the **source of truth**).
2. If the lyric row exists, return the stored data (no external call).
3. If not found, call the external API:
   `https://lrclib.net/api/get?artist_name=...&track_name=...&album_name=...`
   The service sends the request with the exact `User-Agent` header:
   `Power Ampache Lyric Plugin v1.0 (https://power.ampache.dev)`
4. If the external API provides a result, the service:
   - Inserts the full record into the `lyrics` table (DB is updated),
   - Returns the record to the client.
5. If neither DB nor external API returns lyrics, the endpoint responds `404`.

## Project layout

```
fastapi-lyrics-service/
├─ docker-compose.yml # orchestrates web + postgres
├─ db_init/
│ └─ init_db.sql # creates lyrics table and indexes
└─ web/
├─ Dockerfile # build instructions for the python app
├─ requirements.txt # pinned python deps
└─ main.py # API server (FastAPI) - DB+API logic
```


```
## Key files explained

### db_init/init_db.sql
Creates the `lyrics` table (if not present) with these columns:

- `id BIGINT PRIMARY KEY` — unique id for each row (generated from Python by default)
- `name TEXT`
- `trackName TEXT`
- `artistName TEXT`
- `albumName TEXT`
- `duration DOUBLE PRECISION`
- `instrumental BOOLEAN`
- `plainLyrics TEXT` — the raw lyrics text (this is the main content)
- `syncedLyrics JSONB`
- `fetched_at TIMESTAMP WITH TIME ZONE DEFAULT now()`

Also creates:
- A unique index for case-insensitive lookups on `(artistName, trackName, albumName)` (implemented with `lower(trim(...))`).
- A GIN index on `syncedLyrics` for future JSON searching.

**Important Postgres note**: Postgres folds unquoted identifiers to lowercase. Columns declared `plainLyrics` in SQL will end up accessible as `plainlyrics` in queries unless you quoted identifiers everywhere. The code in `main.py` queries the lowercase names (`artistname`, `trackname`, `plainlyrics`) to avoid quoting issues.

### web/Dockerfile
- Based on `python:3.11-slim`.
- Installs system build deps required by `asyncpg`.
- Copies `requirements.txt` and installs Python packages.
- Copies `main.py` and runs `uvicorn main:app --host 0.0.0.0 --port 8000`.

### web/requirements.txt
Pinned versions for reproducibility:

```
fastapi==0.100.0
uvicorn[standard]==0.22.0
asyncpg==0.27.0
aiohttp==3.9.5
python-dotenv==1.0.0
```


### web/main.py
- Connects to Postgres using `asyncpg.create_pool` with startup retry logic.
- `get_lyrics` endpoint follows the exact flow above.
- Uses `aiohttp` to call `https://lrclib.net/api/get` and sends the exact `User-Agent` header:
  `Power Ampache Lyric Plugin v1.0 (https://power.ampache.dev)`
- Inserts fetched records into the DB so the DB remains the source of truth.
- ID generation: current approach generates a big integer ID in Python as `int(time.time() * 1000)` (milliseconds since epoch)..
  - short term update: DB-generated IDs is preferable, alter the table to use `GENERATED AS IDENTITY` and remove the `id` from the insert.

## Running locally (Docker Compose)

From project root:

```bash
# (optional) remove old volumes if you want a fresh DB initialization
docker compose down -v

# build & run
docker compose up --build

`Watch docker compose logs -f web to see the app connect to Postgres.`

Testing the endpoint

Example:
`curl "http://localhost:8000/getlyrics?artist_name=Necrophagist&track_name=Fermented%20Offal%20Discharge"`

If DB did not have the lyric, the service will fetch it from lrclib, insert into DB, and return the JSON object containing plainLyrics.

Next call will return the stored DB result.


The Python ID generator (int(time.time() * 1000)) is robust enough for low-volume inserts but not perfect for extremely high insert-per-ms scenarios. For stronger uniqueness, switch to DB IDENTITY/SERIAL and remove the id from the insert.


# Next improvements (optional)

Replace hardcoded DATABASE_URL and credentials with env vars (.env + env_file in docker-compose).

Use DB-generated IDs (GENERATED ALWAYS AS IDENTITY) and drop Python ID generation.

Add DB upsert (ON CONFLICT) behavior to update existing rows for freshest content from external API to overwrite DB. Right now we insert and do nothing on ID conflicts.

Add request logging and rate-limiting.

Add healthchecks for web and db services in docker-compose.


