from fastapi import FastAPI
from pydantic import BaseModel
import os
import time
import httpx

app = FastAPI(title="Personal Assistant")

OWNER = os.getenv("APP_OWNER", "anonymous")
SECRET_KEY = os.getenv("APP_SECRET", "default_secret")
DATABASE_URL = os.getenv("DATABASE_URL")


class Note(BaseModel):
    text: str
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


@app.get("/")
async def root():
    return {
        "message": f"👋 Привет, {OWNER}!",
        "service": "personal-assistant",
        "version": "1.0",
        "endpoints": ["/me", "/notes", "/weather/{city}", "/secret/{key}"],
    }


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
    return {"status": "healthy", "owner": OWNER, "database": db_status}


@app.get("/me")
async def me():
    return {
        "owner": OWNER,
        "secret_prefix": SECRET_KEY[:6]
        if SECRET_KEY != "default_secret"
        else "NOT_SET",
    }


@app.get("/secret/{key}")
async def secret(key: str):
    if key == SECRET_KEY:
        return {
            "flag": f"LAB2_SUCCESS_{OWNER.upper()}",
            "message": "The secret key is correct!",
        }
    return {
        "error": "The secret key is incorrect",
        "hint": "Check the APP_SECRET environment variable",
    }


WEATHER_CODES: dict[int, str] = {
    0: "☀️ Ясно", 1: "🌤 Малооблачно", 2: "⛅ Переменная облачность",
    3: "☁️ Пасмурно", 45: "🌫 Туман", 48: "🌫 Изморозь",
    51: "🌦 Лёгкая морось", 53: "🌦 Морось", 55: "🌧 Сильная морось",
    61: "🌧 Небольшой дождь", 63: "🌧 Дождь", 65: "🌧 Сильный дождь",
    71: "🌨 Небольшой снег", 73: "🌨 Снег", 75: "❄️ Сильный снег",
    80: "🌦 Ливень", 81: "🌧 Сильный ливень", 82: "⛈ Штормовой ливень",
    95: "⛈ Гроза", 96: "⛈ Гроза с градом", 99: "⛈ Сильная гроза с градом",
}


@app.get("/weather/{city}")
async def weather(city: str):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            geo_resp = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "ru"},
            )
            geo_data = geo_resp.json()

            if not geo_data.get("results"):
                return {"error": f"City «{city}» not found"}

            location = geo_data["results"][0]
            lat = location["latitude"]
            lon = location["longitude"]
            city_name = location.get("name", city)
            country = location.get("country", "")

            weather_resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                },
            )
            weather_data = weather_resp.json()["current"]

            code = weather_data.get("weather_code", -1)

            return {
                "city": city_name,
                "country": country,
                "coordinates": {"lat": lat, "lon": lon},
                "temperature_c": weather_data["temperature_2m"],
                "humidity_pct": weather_data["relative_humidity_2m"],
                "wind_km_h": weather_data["wind_speed_10m"],
                "condition": WEATHER_CODES.get(code, f"Code {code}"),
            }
    except Exception as e:
        return {"error": f"Failed to get weather: {type(e).__name__}: {e}"}


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
        return {
            "status": "saved",
            "note_id": note_id,
            "total": total,
            "storage": "postgres",
        }

    notes.append(note.text)
    return {
        "status": "saved",
        "note_id": len(notes) - 1,
        "total": len(notes),
        "storage": "memory",
    }


@app.get("/notes")
async def list_notes():
    if db_pool is not None:
        conn = db_pool.getconn()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT text FROM notes ORDER BY id")
                rows = [r[0] for r in cur.fetchall()]
        finally:
            db_pool.putconn(conn)
        return {"notes": rows, "count": len(rows), "storage": "postgres"}

    return {"notes": notes, "count": len(notes), "storage": "memory"}
