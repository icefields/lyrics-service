# main.py
import asyncio
import asyncpg
import aiohttp
from fastapi import FastAPI, HTTPException
import time
import json

# NOTE: currently the DB credentials are hardcoded here.
# This must match the DB created by the docker-compose service.
DATABASE_URL = "postgresql://ampache:wSXAlI9oHujY3XmC8AqNjpjKaXuLt7HCP7TSnjyNNOSasgZZyqCWpMNn3Xmg1gC792@db:5432/lyricsdb"

# External API endpoint
LRCLIB_API = "https://lrclib.net/api/get"

OUTGOING_USER_AGENT = "Power Ampache Lyric Plugin v1.0 (https://power.ampache.dev)"

app = FastAPI()
db_pool: asyncpg.pool.Pool | None = None

# -------------------------------
# Database Connection (with retries)
# -------------------------------
async def connect_db(retries: int = 10, delay: float = 2.0):
    global db_pool
    for attempt in range(1, retries + 1):
        try:
            db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
            print("Connected to Postgres")
            return
        except Exception as e:
            print(f"Postgres connection failed (attempt {attempt}/{retries}): {e}")
            await asyncio.sleep(delay)
    raise RuntimeError("Could not connect to Postgres after multiple attempts")

@app.on_event("startup")
async def startup():
    await connect_db()

@app.on_event("shutdown")
async def shutdown():
    global db_pool
    if db_pool:
        await db_pool.close()

# -------------------------------
# Fetch from DB
# -------------------------------

async def get_lyrics_from_db(artist_name: str, track_name: str, album_name: str | None = None):
    """
    Returns plain lyrics string from DB if present, otherwise None.

    Important: Postgres lowercases unquoted identifiers. init_db.sql created columns
    like plainLyrics, artistName, trackName but Postgres stores them as plainlyrics, artistname, trackname.
    We therefore query lowercase column names here.
    """
    global db_pool
    if not db_pool:
        raise HTTPException(status_code=500, detail="DB not initialized")

    # Normalize album_name for comparison (UNIQUE uses COALESCE + trim + lower)
    normalized_album = (album_name or "").lower().strip()

    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM lyrics
            WHERE lower(trim(artistname)) = $1
              AND lower(trim(trackname)) = $2
              AND lower(coalesce(trim(albumname), '')) = $3
            LIMIT 1
            """,
            artist_name.lower().strip(),
            track_name.lower().strip(),
            normalized_album
        )
        # asyncpg returns keys exactly as stored (lowercase), so row keys match column names
        return row if row else None

# -------------------------------
# Fetch from external API (full JSON)
# -------------------------------
async def fetch_lyrics_from_api(artist_name: str, track_name: str, album_name: str | None = None, duration: int | None = None) -> dict | None:
    """
    Calls https://lrclib.net/api/get?artist_name=...&track_name=...&album_name=...
    Returns the parsed JSON dict (the whole record), or None if not found / on non-200.
    """
    params = {
        "artist_name": artist_name,
        "track_name": track_name,
        "album_name": album_name or None,
        "duration" : duration or None
    }

    headers = {
        "User-Agent": OUTGOING_USER_AGENT
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(LRCLIB_API, params=params, timeout=15) as resp:
            if resp.status != 200:
                # external service returned not found or error
                return None
            data = await resp.json()
            # validate basic shape
            if not isinstance(data, dict):
                return None
            # `plainLyrics` is the field we store/return, ensure it exists (may be empty)
            return data

# -------------------------------
# Insert into DB with manual ID (milliseconds since epoch)
# -------------------------------
async def insert_lyrics_to_db(
    artist_name: str,
    track_name: str,
    album_name: str | None,
    name: str | None,
    duration: float | None,
    instrumental: bool | None,
    plain_lyrics: str,
    synced_lyrics: dict | None = None
):
    """
    Inserts a full record into your existing lyrics table.
    Generate a bigint id in Python (ms since epoch) so no schema changes are required.
    """
    global db_pool
    if not db_pool:
        raise HTTPException(status_code=500, detail="DB not initialized")

    # --- FIXES START HERE ---
    # Ensure syncedLyrics is valid JSON or None
    if synced_lyrics in ("", [], {}, None):
        synced_lyrics = None
    else:
        synced_lyrics = json.dumps(synced_lyrics)

    # Ensure duration is stored as an integer (lrclib may send floats like 233.00)
    if duration is not None:
        try:
            duration = int(duration)
        except Exception:
            duration = None

    # Ensure plainLyrics is always a string
    if plain_lyrics is None:
        plain_lyrics = ""

    # Generate a unique ID manually (milliseconds since epoch)
    generated_id = int(time.time() * 1000)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO lyrics(
                id, artistname, trackname, albumname, name, duration, instrumental, plainlyrics, syncedlyrics
            ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
            """,
            generated_id,
            artist_name,
            track_name,
            album_name,
            name,
            duration,
            instrumental,
            plain_lyrics,
            synced_lyrics
        )

# -------------------------------
# API Endpoint: /getlyrics
# -------------------------------
@app.get("/getlyrics")
async def get_lyrics(artist_name: str, track_name: str, album_name: str | None = None, duration: int | None = None):
    """
    Workflow:
      1) Try DB (source-of-truth)
      2) If missing, fetch from lrclib.net
      3) Insert the exact fetched data into DB (DB is updated synchronously)
      4) Return the lyrics
    """
    # 1) DB
    
    record = await get_lyrics_from_db(artist_name, track_name, album_name)
    if record:
        return dict(record)

    # 2) External API
    api_data = await fetch_lyrics_from_api(artist_name, track_name, album_name, duration)
    if not api_data:
        raise HTTPException(status_code=404, detail="Lyrics not found")

    # 3) Normalize fields from API (use keys exactly as API returns)
    album_name = api_data.get("albumName") if album_name is None else album_name
    name = api_data.get("name") or track_name
    duration = api_data.get("duration")
    instrumental = api_data.get("instrumental")
    plain_lyrics = api_data.get("plainLyrics") or ""
    synced_lyrics = api_data.get("syncedLyrics") or None

    # 4) Insert into DB
    await insert_lyrics_to_db(
        artist_name=api_data.get("artistName", artist_name),
        track_name=api_data.get("trackName", track_name),
        album_name=album_name,
        name=name,
        duration=duration,
        instrumental=instrumental,
        plain_lyrics=plain_lyrics,
        synced_lyrics=synced_lyrics
    )

    # 5) Return full API data
    return {
        "id": api_data.get("id"),
        "name": name,
        "trackName": api_data.get("trackName", track_name),
        "artistName": api_data.get("artistName", artist_name),
        "albumName": album_name,
        "duration": duration,
        "instrumental": instrumental,
        "plainLyrics": plain_lyrics,
        "syncedLyrics": synced_lyrics
    }

