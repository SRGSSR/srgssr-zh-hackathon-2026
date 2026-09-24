import asyncio, uuid
from fastapi import APIRouter, Depends, Request
from litellm.proxy.auth.user_api_key_auth import user_api_key_auth
from litellm.integrations.custom_logger import CustomLogger

JOBS = {}
router = APIRouter(dependencies=[Depends(user_api_key_auth)])
_task = None


def _ensure_worker():
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(worker())

@router.post("/v1/deferred/chat/completions", status_code=202)
async def submit(req: Request):
    _ensure_worker()
    body = await req.json()
    jid = "def-" + uuid.uuid4().hex[:8]
    JOBS[jid] = {"status": "queued", "body": body, "tries": 0}
    return {"id": jid, "status": "queued"}

@router.get("/v1/deferred/{jid}")
async def get(jid: str):
    j = JOBS[jid]; return {k: v for k, v in j.items() if k != "body"}

async def worker():
    from litellm.proxy.proxy_server import llm_router
    while True:
        for jid, j in list(JOBS.items()):
            if j["status"] in ("queued", "waiting"):
                j["tries"] += 1
                try:
                    r = await llm_router.acompletion(**j["body"])
                    j.update(status="done", answer=r.choices[0].message.content)
                except Exception as e:
                    j.update(status="waiting", last_error=type(e).__name__)
        await asyncio.sleep(1)

class Plugin(CustomLogger):
    def __init__(self):
        super().__init__()
        from litellm.proxy.proxy_server import app
        app.include_router(router)
        self._task = None

    async def async_pre_call_hook(self, *a, **k):  # lazy start inside the running loop
        return None

plugin = Plugin()

