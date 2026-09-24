"""Tiny OpenAI-compatible mock with fault injection + request counters.

Usage inside the LiteLLM image (fastapi/uvicorn available):
    from mock_openai import start_mocks
    mocks = start_mocks({"mock-ch-1": 9101, "mock-ch-2": 9102, "mock-us-1": 9103})
    mocks["mock-ch-1"].mode = "down"     # up | down (HTTP 503) | slow (sleep then 200) | timeout (sleep 30s after receiving)
    mocks["mock-ch-1"].count              # requests received on /v1/chat/completions
    mocks["mock-ch-1"].requests           # list of received JSON bodies + headers
api_base for LiteLLM: http://127.0.0.1:<port>/v1
"""
import threading, time, asyncio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class Mock:
    def __init__(self, name, port):
        self.name, self.port = name, port
        self.mode, self.count, self.requests = "up", 0, []
        self.slow_seconds, self.timeout_seconds = 2.0, 30.0
        app = FastAPI()

        @app.get("/v1/models")
        async def models():
            return {"object": "list", "data": [{"id": f"{self.name}-model", "object": "model"}]}

        @app.post("/v1/chat/completions")
        async def chat(req: Request):
            body = await req.json()
            self.count += 1
            self.requests.append({"body": body, "headers": dict(req.headers), "t": time.time()})
            if self.mode == "down":
                return JSONResponse({"error": {"message": f"{self.name} down", "type": "server_error"}}, status_code=503)
            if self.mode == "slow":
                await asyncio.sleep(self.slow_seconds)
            if self.mode == "timeout":
                await asyncio.sleep(self.timeout_seconds)
            return {
                "id": f"chatcmpl-{self.name}-{self.count}", "object": "chat.completion", "created": int(time.time()),
                "model": body.get("model", "x") + f"@{self.name}",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": f"hello from {self.name}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }

        self.app = app

    def reset(self):
        self.mode, self.count, self.requests = "up", 0, []


def start_mocks(spec):
    mocks = {}
    for name, port in spec.items():
        m = Mock(name, port)
        server = uvicorn.Server(uvicorn.Config(m.app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        mocks[name] = m
    time.sleep(1.5)
    return mocks
