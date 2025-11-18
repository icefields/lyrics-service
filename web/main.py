# main.py
import asyncio
import asyncpg
import aiohttp
from fastapi import FastAPI, HTTPException
import time

DATABASE_URL = "postgresql://ampache:wSXAlI9oHujY3XmC8AqNjpjKaXuLt7HCP7TSnjyNNOSasgZZyqCWpMNn3Xmg1gC792@db:5432/lyricsdb"

app = FastAPI()
db_pool: asyncpg.pool.Pool | None = None

# -------------------------------
# Database Connection
# -------------------------------
async def connect_db(retries: int = 5, delay: float = 3.0):
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
async def get_lyrics_from_db(artist_name: str, track_name: str):
    global db_pool
    if not db_pool:
        raise HTTPException(status_code=500, detail="DB not initialized")
    async with db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT plainlyrics FROM lyrics WHERE lower(trim(artistname))=$1 AND lower(trim(trackname))=$2",
            artist_name.lower().strip(),
            track_name.lower().strip()
        )
        return row["plainlyrics"] if row else None

# -------------------------------
# Fetch from external API
# -------------------------------
async def fetch_lyrics_from_api(artist_name: str, track_name: str, album_name: str | None = None) -> dict:
    url = f"https://lrclib.net/api/get?artist_name={artist_name}&track_name={track_name}"
    if album_name:
        url += f"&album_name={album_name}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()  # returns the full JSON dict
            return data

# -------------------------------
# Insert into DB with manual ID
# -------------------------------
async def insert_lyrics_to_db(
    artist_name: str,
    track_name: str,
    album_name: str | None,
    name: str,
    duration: float | None,
    instrumental: bool | None,
    lyrics_text: str,
    synced_lyrics: dict | None = None
):
    global db_pool
    if not db_pool:
        raise HTTPException(status_code=500, detail="DB not initialized")

    # Generate a unique ID manually (milliseconds since epoch)
    generated_id = int(time.time() * 1000)

    async with db_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO lyrics(
                id, artistName, trackName, albumName, name, duration, instrumental, plainLyrics, syncedLyrics
            ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)
            """,
            generated_id,
            artist_name,
            track_name,
            album_name,
            name,
            duration,
            instrumental,
            lyrics_text,
            synced_lyrics
        )

# -------------------------------
# API Endpoint
# -------------------------------
@app.get("/getlyrics")
async def get_lyrics(artist_name: str, track_name: str, album_name: str | None = None):
    # Check DB first
    lyrics = await get_lyrics_from_db(artist_name, track_name)
    if lyrics:
        return {"lyrics": lyrics}

    # Fetch from external API
    api_data = await fetch_lyrics_from_api(artist_name, track_name, album_name)
    
    if not api_data:
        raise HTTPException(status_code=404, detail="Lyrics not found")

    # Extract fields
    album_name = api_data.get("albumName") if album_name is None else album_name
    duration = api_data.get("duration")
    instrumental = api_data.get("instrumental")
    lyrics_text = api_data.get("plainLyrics")
    name = api_data.get("trackName") or track_name

    # Insert into DB
    await insert_lyrics_to_db(
        artist_name,
        track_name,
        album_name,
        name,
        duration,
        instrumental,
        lyrics_text,
        None
    )

    return {"lyrics": lyrics_text}

