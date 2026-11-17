import os
import time
import json
import httpx
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Personal Assistant API", version="4.0")

OWNER = os.getenv("APP_OWNER", "anonymous")
SECRET = os.getenv("APP_SECRET", "default_secret")
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL = int(os.getenv("CACHE_TTL", "120"))

try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    REDIS_ENABLED = True
except Exception:
    redis_client = None
    REDIS_ENABLED = False

notes: list[str] = []
db_pool = None

if DATABASE_URL:
    import psycopg2
    from psycopg2.pool import SimpleConnectionPool

    for attempt in range(10):
        try:
            db_pool = SimpleConnectionPool(1, 5, DATABASE_URL)
            break
        except Exception:
            time.sleep(2)

    if db_pool is not None:
        conn = db_pool.getconn()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notes (
                        id SERIAL PRIMARY KEY,
                        text TEXT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                    """
                )
        finally:
            db_pool.putconn(conn)


class Note(BaseModel):
    text: str


WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    51: "Light drizzle",
    61: "Slight rain",
    71: "Slight snow fall",
    95: "Thunderstorm",
}

CITIES = {
    "moscow": {"lat": 55.75, "lon": 37.61, "name": "Moscow", "country": "Russia"},
    "london": {"lat": 51.50, "lon": -0.12, "name": "London", "country": "United Kingdom"},
    "paris": {"lat": 48.85, "lon": 2.35, "name": "Paris", "country": "France"},
}


@app.get("/")
async def root():
    return {"message": f"Hello from Personal Assistant of {OWNER}!"}


@app.get("/health")
async def health():
    db_status = "not_configured"
    if db_pool is not None:
        try:
            conn = db_pool.getconn()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                db_status = "connected"
            finally:
                db_pool.putconn(conn)
        except Exception as e:
            db_status = f"error: {type(e).__name__}"

    redis_status = "connected" if REDIS_ENABLED else "disconnected"
    return {"status": "healthy", "owner": OWNER, "database": db_status, "redis": redis_status}


@app.get("/me")
async def me():
    return {"owner": OWNER, "secret_prefix": SECRET[:6]}


@app.post("/notes")
async def create_note(note: Note):
    if db_pool is not None:
        conn = db_pool.getconn()
        try:
            with conn, conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO notes (text) VALUES (%s) RETURNING id",
                    (note.text,),
                )
                note_id = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM notes")
                total = cur.fetchone()[0]
        finally:
            db_pool.putconn(conn)
        return {"status": "saved", "note_id": note_id, "total": total, "storage": "postgres"}

    notes.append(note.text)
    return {"status": "saved", "note_id": len(notes) - 1, "total": len(notes), "storage": "memory"}


@app.get("/notes")
async def get_notes():
    if db_pool is not None:
        conn = db_pool.getconn()
        try:
            with conn, conn.cursor() as cur:
                cur.execute("SELECT id, text, created_at FROM notes ORDER BY id")
                rows = cur.fetchall()
                items = [{"id": r[0], "text": r[1], "created_at": r[2].isoformat()} for r in rows]
        finally:
            db_pool.putconn(conn)
        return {"notes": items, "storage": "postgres"}
    return {"notes": notes, "storage": "memory"}


@app.get("/weather/{city}")
async def weather(city: str):
    city_key = city.lower()
    if city_key not in CITIES:
        raise HTTPException(status_code=404, detail="City not found in supported list (Moscow, London, Paris)")

    cache_key = f"weather:{OWNER}:{city_key}"

    if REDIS_ENABLED:
        cached = redis_client.get(cache_key)
        if cached:
            data = json.loads(cached)
            data["source"] = "cache"
            return data

    city_info = CITIES[city_key]
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={city_info['lat']}&longitude={city_info['lon']}"
        "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
    )

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(url, timeout=5.0)
            resp.raise_for_status()
            weather_data = resp.json().get("current", {})
        except Exception:
            raise HTTPException(status_code=503, detail="Failed to fetch external weather data")

    code = weather_data.get("weather_code", 0)
    result = {
        "city": city_info["name"],
        "country": city_info["country"],
        "temperature_c": weather_data.get("temperature_2m"),
        "humidity_pct": weather_data.get("relative_humidity_2m"),
        "wind_km_h": weather_data.get("wind_speed_10m"),
        "condition": WEATHER_CODES.get(code, f"Code {code}"),
        "source": "api",
    }

    if REDIS_ENABLED:
        redis_client.setex(cache_key, CACHE_TTL, json.dumps(result))

    return result


@app.get("/cache/stats")
async def cache_stats():
    if not REDIS_ENABLED:
        return {"status": "redis disabled"}
    keys = redis_client.keys(f"weather:{OWNER}:*")
    return {
        "owner": OWNER,
        "ttl_seconds": CACHE_TTL,
        "cached_count": len(keys),
        "cached_cities": sorted(k.split(":")[-1] for k in keys),
    }


@app.get("/secret/{key}")
async def secret_flag(key: str):
    if key == SECRET:
        return {"flag": f"LAB4_SUCCESS_{OWNER.upper()}"}
    raise HTTPException(status_code=403, detail="Invalid secret key")
