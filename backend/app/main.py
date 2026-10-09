import os
import psycopg
from fastapi import FastAPI, Response

app = FastAPI(title="FieldPilot API")

@app.get("/health")
def health(response: Response):
    try:
        with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=3) as conn:
            postgis = conn.execute("SELECT PostGIS_Version()").fetchone()[0]
        return {"status": "ok", "postgis": postgis}
    except Exception as e:
        response.status_code = 503
        return {"status": "error", "detail": str(e)}