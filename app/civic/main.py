import os
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from . import db, endpoints, i18n, sync, timeline
from .letters import LANGUAGE_NAMES, SAMPLES, SERVICES, sensitive_topics, service_view

SAMPLES_DIR = Path(os.environ.get("SAMPLES_DIR", "/samples"))
HERE = Path(__file__).parent

app = FastAPI(title="Commune letter helper")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")


def _when(ts: float, lang: str = "en") -> str:
    import datetime as dt
    d = dt.datetime.fromtimestamp(ts, timeline.LOCAL_TZ)
    today = dt.datetime.now(timeline.LOCAL_TZ).date()
    return (i18n.t(lang, "common.today") if d.date() == today else f"{d.day}.{d.month}.") + d.strftime(", %H:%M")


templates.env.filters["when"] = _when
templates.env.filters["marked"] = i18n.marked
templates.env.filters["capitalize_first"] = lambda s: s[:1].upper() + s[1:]
templates.env.globals["v"] = str(int(__import__("time").time()))  # cache-busting for static files
templates.env.globals["shared_demo"] = os.environ.get("SHARED_DEMO") == "1"  # the shared online demo


@app.on_event("startup")
async def startup():
    db.init()


@app.middleware("http")
async def language(request: Request, call_next):
    """The page's language: ?lang= (remembered in a cookie), else the browser's, else English."""
    asked = request.query_params.get("lang")
    request.state.lang = i18n.pick(asked, request.cookies.get("lang"), request.headers.get("accept-language", ""))
    response = await call_next(request)
    if asked in i18n.UI_LANGUAGES and request.cookies.get("lang") != asked:
        response.set_cookie("lang", asked, max_age=365 * 24 * 3600, samesite="lax")
    return response


def _render(request: Request, name: str, context: dict):
    lang = request.state.lang
    base = {"lang": lang, "t": lambda key, **kw: i18n.t(lang, key, **kw), "ui_languages": i18n.UI_LANGUAGES,
            "strings": i18n.strings(lang)}
    return templates.TemplateResponse(request, name, {**base, **context})


def _samples():
    return sorted(p.name for p in SAMPLES_DIR.glob("*.txt")) if SAMPLES_DIR.exists() else []


async def _view(letter_id: str):
    job = await sync.refresh(letter_id)
    if not job:
        raise HTTPException(404, "job not found")
    evs = await sync.events(letter_id)
    return job, evs


SHARED_DEMO = os.environ.get("SHARED_DEMO") == "1"
LETTERS_PER_HOUR = int(os.environ.get("SHARED_DEMO_LETTERS_PER_HOUR", "100"))
_recent_by_ip: dict = {}


def _check_rate(request: Request) -> None:
    """On the open shared demo, limit how many letters one address can send per hour,
    so nobody uses up the Public AI key's quota."""
    if not SHARED_DEMO:
        return
    import time as _t
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "?")).split(",")[0].strip()
    now = _t.time()
    recent = [t for t in _recent_by_ip.get(ip, []) if now - t < 3600]
    if len(recent) >= LETTERS_PER_HOUR:
        raise HTTPException(429, i18n.t(request.state.lang, "error.rate"))
    _recent_by_ip[ip] = recent + [now]


async def _create(letter: str, language: str, service: str = "social") -> str:
    letter_id = db.create(letter, language, service if service in SERVICES else "social")
    await sync.submit(letter_id)
    return letter_id


# ------------------------------------------------------------------------- pages
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    jobs = db.recent(6)
    for j in jobs:
        if j["status"] not in db.TERMINAL:
            j["status"] = (await sync.refresh(j["id"]) or j)["status"]
    lang = request.state.lang
    samples = []
    for f in _samples():
        sender, subject, service = SAMPLES.get(f, ("", f, "social"))
        samples.append({"file": f, "sender": i18n.t(lang, sender), "subject": i18n.t(lang, subject), "service": service})
    return _render(request, "index.html", {
        "languages": LANGUAGE_NAMES, "samples": samples, "jobs": jobs,
        "services": {key: service_view(key, lang) for key in SERVICES},
        "explain_in": lang if lang in LANGUAGE_NAMES else "it",
    })


@app.post("/jobs")
async def create_job_form(request: Request, letter: str = Form(...), language: str = Form("it"), service: str = Form("social")):
    if not letter.strip():
        raise HTTPException(400, "empty letter")
    _check_rate(request)
    return RedirectResponse(f"/jobs/{await _create(letter.strip(), language, service)}", status_code=303)


@app.get("/jobs/{letter_id}", response_class=HTMLResponse)
async def job_page(request: Request, letter_id: str):
    job = db.get(letter_id)
    if not job:
        raise HTTPException(404, "job not found")
    lang = request.state.lang
    return _render(request, "job.html", {
        "job": job, "language_name": LANGUAGE_NAMES.get(job["language"], job["language"]),
        "topics": [i18n.t(lang, key) for key in sensitive_topics(job["letter"])],
        "service": service_view(job["service"], lang),
    })


@app.post("/jobs/{letter_id}/again")
async def again_form(request: Request, letter_id: str):
    job = db.get(letter_id)
    if not job:
        raise HTTPException(404, "job not found")
    _check_rate(request)
    return RedirectResponse(f"/jobs/{await _create(job['letter'], job['language'], job['service'])}", status_code=303)


@app.get("/demo", response_class=HTMLResponse)
async def demo_page(request: Request):
    return _render(request, "demo.html", {"jobs": db.recent(10)})


@app.post("/demo/endpoint/{endpoint_id}/{mode}")
async def demo_set(endpoint_id: str, mode: str):
    await endpoints.set_mode(endpoint_id, mode)
    return {"ok": True}


@app.post("/demo/break-approved")
async def demo_break_approved():
    await endpoints.set_mode_many([e["id"] for e in endpoints.load() if e["approved"]], "down")
    return {"ok": True}


@app.post("/demo/break-swiss-eu")
async def demo_break_swiss_eu():
    await endpoints.set_mode_many([e["id"] for e in endpoints.load() if e["jurisdiction"] in ("CH", "EU")], "down")
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
    service: str = "social"


class ConsentIn(BaseModel):
    jurisdictions: list
    statement: str


@app.post("/api/jobs")
async def api_create(request: Request, job: JobIn):
    _check_rate(request)
    return {"id": await _create(job.letter, job.language, job.service)}


@app.post("/api/jobs/{letter_id}/consent")
async def api_consent(letter_id: str, body: ConsentIn):
    error = await sync.consent(letter_id, body.jurisdictions, body.statement)
    if error:
        raise HTTPException(409, error)
    return {"ok": True}


@app.get("/api/jobs/{letter_id}")
async def api_job(letter_id: str):
    job, evs = await _view(letter_id)
    job.pop("letter", None)
    return {**job, "summary": timeline.summary(evs)}


@app.get("/api/jobs/{letter_id}/journey")
async def api_journey(request: Request, letter_id: str):
    """Everything the letter page shows, refreshed every second by static/job.js, in the page's language."""
    lang = request.state.lang
    job, evs = await _view(letter_id)
    eps = endpoints.by_id(lang)
    shown = {k: job.get(k) for k in ("id", "status", "status_reason", "next_retry_at", "result", "language", "served_by", "runs",
                                      "service", "consent_options", "consent")}
    shown["status_reason"] = i18n.reason(lang, shown["status_reason"])
    return {
        "job": shown,
        "service": service_view(job["service"], lang),
        "served_by_name": (eps.get(job.get("served_by") or "") or {}).get("name"),
        "served_by_kind": (eps.get(job.get("served_by") or "") or {}).get("kind"),
        "receipt": timeline.receipt(evs, eps, lang),
        "stops": timeline.compact(timeline.journey(evs, eps, lang), lang),
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
async def api_endpoints(request: Request):
    return await endpoints.status(request.state.lang)


@app.get("/healthz")
async def healthz():
    return {"ok": True}
