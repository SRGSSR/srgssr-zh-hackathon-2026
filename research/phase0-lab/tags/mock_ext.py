"""Extended OpenAI-compatible mock for tag experiments (does not modify ../mock_openai.py).

Modes: up | down (503) | ctx (400 context_length_exceeded) | policy (400 content_policy_violation)
       | timeout (sleep 30s after receiving) | ratelimit (429)
"""
import threading, time, asyncio
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class Mock:
    def __init__(self, name, port):
        self.name, self.port = name, port
        self.mode, self.count, self.requests = "up", 0, []
        self.timeout_seconds = 30.0
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
            if self.mode == "ratelimit":
                return JSONResponse({"error": {"message": f"{self.name} rate limited", "type": "rate_limit"}}, status_code=429)
            if self.mode == "ctx":
                return JSONResponse({"error": {"message": "This model's maximum context length is 10 tokens. However, your messages resulted in 99999 tokens.",
                                               "type": "invalid_request_error", "code": "context_length_exceeded"}}, status_code=400)
            if self.mode == "policy":
                return JSONResponse({"error": {"message": "Your request was rejected as a result of our safety system (content_policy_violation).",
                                               "type": "invalid_request_error", "code": "content_policy_violation"}}, status_code=400)
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
