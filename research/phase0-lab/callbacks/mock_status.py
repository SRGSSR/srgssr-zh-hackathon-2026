"""OpenAI-compatible mock with arbitrary HTTP status injection (the shared mock_openai.py only does 503).
mode: "up" | <int status code, e.g. 429> | "timeout" (sleep 30s after receiving). Counters like mock_openai."""
import asyncio, threading, time
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class StatusMock:
    def __init__(self, name, port):
        self.name, self.port, self.mode, self.count, self.requests = name, port, "up", 0, []
        app = FastAPI()

        @app.post("/v1/chat/completions")
        async def chat(req: Request):
            body = await req.json()
            self.count += 1
            self.requests.append({"t": time.time(), "mode": self.mode})
            if isinstance(self.mode, int):
                return JSONResponse({"error": {"message": f"{self.name} {self.mode}", "type": "mock"}}, status_code=self.mode)
            if self.mode == "timeout":
                await asyncio.sleep(30)
            return {"id": f"chatcmpl-{self.name}-{self.count}", "object": "chat.completion", "created": int(time.time()),
                    "model": body.get("model", "x") + f"@{self.name}",
                    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": f"hello from {self.name}"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

        self.app = app

    def reset(self):
        self.mode, self.count, self.requests = "up", 0, []


def start_status_mocks(spec):
    out = {}
    for name, port in spec.items():
        m = StatusMock(name, port)
        srv = uvicorn.Server(uvicorn.Config(m.app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=srv.run, daemon=True).start()
        out[name] = m
    time.sleep(1.5)
    return out
