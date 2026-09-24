import asyncio
import hmac
import os
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import db, endpoints, timeline, worker
from .llm import LANGUAGES

INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
# Endpoints that list jobs across citizens exist only for the test bench.
TEST_API = os.environ.get("ENABLE_TEST_API", "0") == "1"
SAMPLES_DIR = Path(os.environ.get("SAMPLES_DIR", "/samples"))
HERE = Path(__file__).parent

app = FastAPI(title="Commune letter helper")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


@app.on_event("startup")
async def startup():
    db.init()
    app.state.worker = asyncio.create_task(worker.loop())


def _samples():
    return sorted(p.name for p in SAMPLES_DIR.glob("*.txt")) if SAMPLES_DIR.exists() else []


def _job_view(job_id: str):
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    evs = db.events(job_id)
    eps = endpoints.by_id()
    return job, timeline.rows(evs, eps), timeline.summary(evs)


# ------------------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        request, "index.html", {"languages": LANGUAGES, "samples": _samples(), "jobs": db.list_jobs()}
    )


@app.post("/jobs")
async def create_job_form(letter: str = Form(...), language: str = Form("it")):
    if not letter.strip():
        raise HTTPException(400, "empty letter")
    job_id = db.create_job(letter.strip(), language)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str):
    job, rows, summ = _job_view(job_id)
    return templates.TemplateResponse(
        request, "job.html", {"job": job, "rows": rows, "summary": summ, "languages": LANGUAGES, "endpoints": await endpoints.status()}
    )


@app.get("/jobs/{job_id}/panel", response_class=HTMLResponse)
async def job_panel(request: Request, job_id: str):
    job, rows, summ = _job_view(job_id)
    return templates.TemplateResponse(request, "_job_panel.html", {"job": job, "rows": rows, "summary": summ, "languages": LANGUAGES})


@app.post("/jobs/{job_id}/wake")
async def wake_form(job_id: str):
    worker.wake(job_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.get("/demo", response_class=HTMLResponse)
async def demo_page(request: Request):
    return templates.TemplateResponse(request, "demo.html", {"endpoints": await endpoints.status(), "jobs": db.list_jobs(10)})


@app.get("/demo/panel", response_class=HTMLResponse)
async def demo_panel(request: Request):
    return templates.TemplateResponse(request, "_endpoints.html", {"endpoints": await endpoints.status()})


@app.post("/demo/endpoint/{endpoint_id}/{mode}", response_class=HTMLResponse)
async def demo_set(request: Request, endpoint_id: str, mode: str):
    await endpoints.set_mode(endpoint_id, mode)
    return await demo_panel(request)


@app.post("/demo/break-approved", response_class=HTMLResponse)
async def demo_break_approved(request: Request):
    await endpoints.set_mode_many([e["id"] for e in endpoints.load() if e["approved"]], "down")
    return await demo_panel(request)


@app.post("/demo/restore-all", response_class=HTMLResponse)
async def demo_restore_all(request: Request):
    await endpoints.set_mode_many([e["id"] for e in endpoints.load()], "up")
    return await demo_panel(request)


@app.post("/demo/reset", response_class=HTMLResponse)
async def demo_reset(request: Request):
    await endpoints.reset_all()
    return await demo_panel(request)


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
    return {"id": db.create_job(job.letter, job.language)}


@app.get("/api/jobs/{job_id}")
async def api_job(job_id: str):
    job, _, summ = _job_view(job_id)
    job.pop("letter", None)
    return {**job, "summary": summ}


@app.get("/api/jobs/{job_id}/events")
async def api_job_events(job_id: str):
    return db.events(job_id)


@app.post("/api/jobs/{job_id}/wake")
async def api_wake(job_id: str):
    worker.wake(job_id)
    return {"ok": True}


@app.post("/api/jobs/{job_id}/cancel")
async def api_cancel(job_id: str):
    return {"cancelled": db.cancel_job(job_id)}


@app.get("/api/pending")
async def api_pending():
    if not TEST_API:
        raise HTTPException(404)
    return db.pending_job_ids()


@app.post("/jobs/{job_id}/cancel")
async def cancel_form(job_id: str):
    db.cancel_job(job_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@app.get("/api/endpoints")
async def api_endpoints():
    return await endpoints.status()


@app.post("/internal/events")
async def internal_events(request: Request):
    token = request.headers.get("x-internal-token", "")
    if not INTERNAL_TOKEN or not hmac.compare_digest(token.encode(), INTERNAL_TOKEN.encode()):
        raise HTTPException(403)
    e = await request.json()
    db.add_event(e.get("job_id"), "gateway", e)
    return {"ok": True}


@app.get("/healthz")
async def healthz():
    return {"ok": True}
