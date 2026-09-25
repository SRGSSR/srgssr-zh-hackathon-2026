import os
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import db, endpoints, sync, timeline
from .letters import LANGUAGE_NAMES, SAMPLES, sensitive_topics

SAMPLES_DIR = Path(os.environ.get("SAMPLES_DIR", "/samples"))
HERE = Path(__file__).parent

app = FastAPI(title="Commune letter helper")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


def _when(ts: float) -> str:
    import datetime as dt
    d = dt.datetime.fromtimestamp(ts, timeline.LOCAL_TZ)
    today = dt.datetime.now(timeline.LOCAL_TZ).date()
    return ("today, " if d.date() == today else d.strftime("%-d %b, ")) + d.strftime("%H:%M")


templates.env.filters["when"] = _when


@app.on_event("startup")
async def startup():
    db.init()


def _samples():
    return sorted(p.name for p in SAMPLES_DIR.glob("*.txt")) if SAMPLES_DIR.exists() else []


async def _view(letter_id: str):
    job = await sync.refresh(letter_id)
    if not job:
        raise HTTPException(404, "job not found")
    evs = await sync.events(letter_id)
    return job, evs


async def _create(letter: str, language: str) -> str:
    letter_id = db.create(letter, language)
    await sync.submit(letter_id)
    return letter_id


# ------------------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    jobs = db.recent(6)
    for j in jobs:
        if j["status"] not in db.TERMINAL:
            j["status"] = (await sync.refresh(j["id"]) or j)["status"]
    samples = [{"file": f, "sender": SAMPLES.get(f, ("", f))[0], "subject": SAMPLES.get(f, ("", f))[1]} for f in _samples()]
    return templates.TemplateResponse(request, "index.html", {"languages": LANGUAGE_NAMES, "samples": samples, "jobs": jobs})


@app.post("/jobs")
async def create_job_form(letter: str = Form(...), language: str = Form("it")):
    if not letter.strip():
        raise HTTPException(400, "empty letter")
    return RedirectResponse(f"/jobs/{await _create(letter.strip(), language)}", status_code=303)


@app.get("/jobs/{letter_id}", response_class=HTMLResponse)
async def job_page(request: Request, letter_id: str):
    job = db.get(letter_id)
    if not job:
        raise HTTPException(404, "job not found")
    return templates.TemplateResponse(
        request, "job.html",
        {"job": job, "language_name": LANGUAGE_NAMES.get(job["language"], job["language"]), "topics": sensitive_topics(job["letter"])},
    )


@app.post("/jobs/{letter_id}/again")
async def again_form(letter_id: str):
    job = db.get(letter_id)
    if not job:
        raise HTTPException(404, "job not found")
    return RedirectResponse(f"/jobs/{await _create(job['letter'], job['language'])}", status_code=303)


@app.get("/demo", response_class=HTMLResponse)
async def demo_page(request: Request):
    return templates.TemplateResponse(request, "demo.html", {"jobs": db.recent(10)})


@app.post("/demo/endpoint/{endpoint_id}/{mode}")
async def demo_set(endpoint_id: str, mode: str):
    await endpoints.set_mode(endpoint_id, mode)
    return {"ok": True}


@app.post("/demo/break-approved")
async def demo_break_approved():
    await endpoints.set_mode_many([e["id"] for e in endpoints.load() if e["approved"]], "down")
    return {"ok": True}


@app.post("/demo/restore-all")
async def demo_restore_all():
    await endpoints.set_mode_many([e["id"] for e in endpoints.load()], "up")
    return {"ok": True}


@app.post("/demo/reset")
async def demo_reset():
    await endpoints.reset_all()
    return {"ok": True}


@app.get("/samples/{name}", response_class=PlainTextResponse)
async def sample(name: str):
    if name not in _samples():
        raise HTTPException(404)
    return (SAMPLES_DIR / name).read_text()


# ------------------------------------------------------------------ JSON API
class JobIn(BaseModel):
    letter: str
    language: str = "it"


@app.post("/api/jobs")
async def api_create(job: JobIn):
    return {"id": await _create(job.letter, job.language)}


@app.get("/api/jobs/{letter_id}")
async def api_job(letter_id: str):
    job, evs = await _view(letter_id)
    job.pop("letter", None)
    return {**job, "summary": timeline.summary(evs)}


@app.get("/api/jobs/{letter_id}/journey")
async def api_journey(letter_id: str):
    """Everything the letter page shows, refreshed every second by static/job.js."""
    job, evs = await _view(letter_id)
    eps = endpoints.by_id()
    return {
        "job": {k: job.get(k) for k in ("id", "status", "status_reason", "next_retry_at", "result", "language", "served_by", "runs")},
        "served_by_name": (eps.get(job.get("served_by") or "") or {}).get("name"),
        "served_by_kind": (eps.get(job.get("served_by") or "") or {}).get("kind"),
        "receipt": timeline.receipt(evs, eps),
        "stops": timeline.journey(evs, eps),
    }


@app.get("/api/jobs/{letter_id}/events")
async def api_job_events(letter_id: str):
    if not db.get(letter_id):
        raise HTTPException(404)
    return await sync.events(letter_id)


@app.post("/api/jobs/{letter_id}/wake")
async def api_wake(letter_id: str):
    await sync.wake(letter_id)
    return {"ok": True}


@app.post("/api/jobs/{letter_id}/cancel")
async def api_cancel(letter_id: str):
    await sync.cancel(letter_id)
    return {"ok": True}


@app.get("/api/endpoints")
async def api_endpoints():
    return await endpoints.status()


@app.get("/healthz")
async def healthz():
    return {"ok": True}
