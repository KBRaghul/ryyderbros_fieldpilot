"""Field Pilot API: serves field data, verified reports, and chat to the React frontend."""
import os
import time
import uuid

import psycopg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.agent.chat import ChatSession
from app.agent.context import field_context
from app.agent.report import generate_report
from app.tools import custom_fields
from app.tools.sentinel import FIELDS_DIR, load_field

app = FastAPI(title="Field Pilot API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_QUESTIONS = 15          # chat questions per session, protects the LLM budget
REPORT_TTL_S = 24 * 3600    # reuse a field's report for 24 hours
_reports = {}               # field_id -> (timestamp, report)
_sessions = {}              # session_id -> {"field_id", "session", "used"}


def field_ids():
    return sorted(p.stem for p in FIELDS_DIR.glob("*.geojson"))


def describe(fid):
    if custom_fields.is_custom_id(fid):
        p = load_field(fid)["properties"]
        return {"id": fid, "label": f"My field ({p['crop']})",
                "county": f"{p['county']} County", "crop": p["crop"], "custom": True}
    county, crop, _ = fid.split("_")
    return {"id": fid, "label": f"{county.title()} County {crop.title()}",
            "county": f"{county.title()} County", "crop": crop}


def require_field(fid):
    """Demo fields, and drawn fields once their analysis is ready."""
    if fid in field_ids():
        return
    if custom_fields.is_custom_id(fid) and custom_fields.is_ready(fid):
        return
    raise HTTPException(status_code=404, detail="Unknown field")


@app.get("/health")
def health(response: Response):
    url = os.getenv("DATABASE_URL")
    if not url:
        return {"status": "ok"}
    try:
        with psycopg.connect(url, connect_timeout=3) as conn:
            postgis = conn.execute("SELECT PostGIS_Version()").fetchone()[0]
        return {"status": "ok", "postgis": postgis}
    except Exception as e:
        response.status_code = 503
        return {"status": "error", "detail": str(e)}


@app.get("/api/fields")
def list_fields():
    return [describe(f) for f in field_ids()]


@app.get("/api/fields/{fid}")
def get_field(fid: str):
    require_field(fid)
    return {**describe(fid), "context": field_context(fid)}


@app.post("/api/fields/{fid}/report")
def report(fid: str):
    require_field(fid)
    cached = _reports.get(fid)
    if cached and time.time() - cached[0] < REPORT_TTL_S:
        return cached[1]
    result = generate_report(fid)
    _reports[fid] = (time.time(), result)
    return result


class CustomFieldRequest(BaseModel):
    geometry: dict
    crop: str


def visitor(request: Request):
    """The visitor's address. Behind Render's proxy it is the first X-Forwarded-For entry."""
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",")[0].strip() or (request.client.host if request.client else "unknown")


@app.post("/api/custom-fields", status_code=202)
def create_custom_field(req: CustomFieldRequest, request: Request):
    """Validate a drawn field and start its analysis. Poll GET /api/custom-fields/{id} for the result."""
    try:
        fid, status = custom_fields.submit(req.geometry, req.crop, visitor(request))
    except custom_fields.FieldError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"id": fid, "status": status}


@app.get("/api/custom-fields/{fid}")
def custom_field_status(fid: str):
    result = custom_fields.status(fid)
    if not result:
        raise HTTPException(status_code=404, detail="Unknown field")
    if result["status"] == "ready":
        result["field"] = describe(fid)
    return result


class ChatRequest(BaseModel):
    field_id: str
    question: str
    session_id: str | None = None


@app.post("/api/chat")
def chat(req: ChatRequest):
    require_field(req.field_id)
    question = req.question.strip()
    if not question or len(question) > 500:
        raise HTTPException(status_code=400, detail="A question must have 1 to 500 characters.")

    sid = req.session_id
    s = _sessions.get(sid)
    if not s or s["field_id"] != req.field_id:
        sid = uuid.uuid4().hex
        s = _sessions[sid] = {"field_id": req.field_id, "session": ChatSession(req.field_id), "used": 0}
    if s["used"] >= MAX_QUESTIONS:
        raise HTTPException(status_code=429, detail="You have reached the question limit for this session.")

    answer = s["session"].ask(question)
    s["used"] += 1
    return {"session_id": sid, "questions_left": MAX_QUESTIONS - s["used"], **answer}



from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def serve_react(path: str):
        """Serve built React files, and index.html for every other page."""
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        file = STATIC_DIR / path
        if path and file.is_file():
            return FileResponse(file)
        return FileResponse(STATIC_DIR / "index.html")