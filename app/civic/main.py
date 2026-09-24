import os
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import db, endpoints, sync, timeline
from .llm import LANGUAGES

SAMPLES_DIR = Path(os.environ.get("SAMPLES_DIR", "/samples"))
HERE = Path(__file__).parent

app = FastAPI(title="Commune letter helper")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


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
    return job, timeline.rows(evs, endpoints.by_id()), timeline.summary(evs), evs


async def _create(letter: str, language: str) -> str:
    letter_id = db.create(letter, language)
    await sync.submit(letter_id)
    return letter_id


# ------------------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    jobs = db.recent()
    for j in jobs[:10]:
        if j["status"] not in db.TERMINAL:
            j["status"] = (await sync.refresh(j["id"]) or j)["status"]
    return templates.TemplateResponse(request, "index.html", {"languages": LANGUAGES, "samples": _samples(), "jobs": jobs})


@app.post("/jobs")
async def create_job_form(letter: str = Form(...), language: str = Form("it")):
    if not letter.strip():
        raise HTTPException(400, "empty letter")
    return RedirectResponse(f"/jobs/{await _create(letter.strip(), language)}", status_code=303)


@app.get("/jobs/{letter_id}", response_class=HTMLResponse)
async def job_page(request: Request, letter_id: str):
    job, rows, summ, _ = await _view(letter_id)
    return templates.TemplateResponse(
        request, "job.html", {"job": job, "rows": rows, "summary": summ, "languages": LANGUAGES, "endpoints": await endpoints.status()}
    )


@app.get("/jobs/{letter_id}/panel", response_class=HTMLResponse)
async def job_panel(request: Request, letter_id: str):
    job, rows, summ, _ = await _view(letter_id)
    return templates.TemplateResponse(request, "_job_panel.html", {"job": job, "rows": rows, "summary": summ, "languages": LANGUAGES})


@app.post("/jobs/{letter_id}/wake")
async def wake_form(letter_id: str):
    await sync.wake(letter_id)
    return RedirectResponse(f"/jobs/{letter_id}", status_code=303)


@app.post("/jobs/{letter_id}/cancel")
async def cancel_form(letter_id: str):
    await sync.cancel(letter_id)
    return RedirectResponse(f"/jobs/{letter_id}", status_code=303)


@app.get("/demo", response_class=HTMLResponse)
async def demo_page(request: Request):
    return templates.TemplateResponse(request, "demo.html", {"endpoints": await endpoints.status(), "jobs": db.recent(10)})


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
    return {"id": await _create(job.letter, job.language)}


@app.get("/api/jobs/{letter_id}")
async def api_job(letter_id: str):
    job, _, summ, _ = await _view(letter_id)
    job.pop("letter", None)
    return {**job, "summary": summ}


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
