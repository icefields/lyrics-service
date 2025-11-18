import httpx

artist_name = "Necrophagist"
track_name = "Fermented Offal Discharge"
album_name = ""

async def test_api():
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://lrclib.net/api/get",
            params={"artist_name": artist_name, "track_name": track_name, "album_name": album_name}
        )
        print(r.status_code)
        print(r.json())

import asyncio
asyncio.run(test_api())

