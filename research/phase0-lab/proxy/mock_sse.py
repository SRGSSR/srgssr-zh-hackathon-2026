"""OpenAI-compatible mock for proxy experiments (same interface as ../mock_openai.py, plus):

- SSE streaming when body.stream is true
- every response carries `x-mock-name: <name>` and `x-ratelimit-remaining-requests: 99`
  so we can see which provider headers the proxy passes through (llm_provider-*)
- modes: up | down (503) | slow (sleep slow_seconds, then 200) | timeout (sleep timeout_seconds after
  receiving the request) | midstream (stream 2 chunks then drop the connection with an error)
  | midstream_err (stream 2 chunks then an in-band SSE `data: {"error": ...}` event)
- .count / .requests / .reset() like mock_openai.Mock

api_base for LiteLLM: http://127.0.0.1:<port>/v1
"""
import asyncio
import json
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


class Mock:
    def __init__(self, name, port):
        self.name, self.port = name, port
        self.mode, self.count, self.requests = "up", 0, []
        self.slow_seconds, self.timeout_seconds = 2.0, 30.0
        app = FastAPI()
        hdrs = {"x-mock-name": name, "x-ratelimit-remaining-requests": "99"}

        @app.get("/v1/models")
        async def models():
            return {"object": "list", "data": [{"id": f"{self.name}-model", "object": "model"}]}

        @app.post("/v1/chat/completions")
        async def chat(req: Request):
            body = await req.json()
            self.count += 1
            self.requests.append({"body": body, "headers": dict(req.headers), "t": time.time()})
            if self.mode == "down":
                return JSONResponse({"error": {"message": f"{self.name} down", "type": "server_error"}},
                                    status_code=503, headers=hdrs)
            if self.mode == "slow":
                await asyncio.sleep(self.slow_seconds)
            if self.mode == "timeout":
                await asyncio.sleep(self.timeout_seconds)
            model = body.get("model", "x") + f"@{self.name}"
            cid = f"chatcmpl-{self.name}-{self.count}"
            if body.get("stream"):
                async def gen():
                    for i, piece in enumerate(["hello ", "from ", self.name]):
                        if self.mode == "midstream" and i == 2:
                            raise RuntimeError("midstream failure")  # abrupt connection drop
                        if self.mode == "midstream_err" and i == 2:
                            # provider-style in-band SSE error event after 2 content chunks
                            yield "data: " + json.dumps({"error": {"message": f"{self.name} overloaded mid-stream",
                                                                   "type": "server_error", "code": 503}}) + "\n\n"
                            return
                        chunk = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
                                 "model": model,
                                 "choices": [{"index": 0, "delta": {"role": "assistant", "content": piece},
                                              "finish_reason": None}]}
                        yield f"data: {json.dumps(chunk)}\n\n"
                        await asyncio.sleep(0.05)
                    last = {"id": cid, "object": "chat.completion.chunk", "created": int(time.time()), "model": model,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 3, "total_tokens": 4}}
                    yield f"data: {json.dumps(last)}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(gen(), media_type="text/event-stream", headers=hdrs)
            return JSONResponse({
                "id": cid, "object": "chat.completion", "created": int(time.time()),
                "model": model,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": f"hello from {self.name}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }, headers=hdrs)

        @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
        async def other(path: str, req: Request):
            # any non-chat endpoint (responses, completions, embeddings, health probes, ...) is recorded too:
            # "data reached this provider" must count regardless of the endpoint
            raw = await req.body()
            self.other.append({"path": "/" + path, "method": req.method, "body": raw[:300].decode("utf-8", "replace")})
            return JSONResponse({"error": {"message": f"{self.name}: /{path} not implemented"}}, status_code=404,
                                headers=hdrs)

        self.app = app
        self.other = []

    @property
    def total(self):
        return self.count + len(self.other)

    def reset(self):
        self.mode, self.count, self.requests, self.other = "up", 0, [], []


def start_mocks(spec):
    mocks = {}
    for name, port in spec.items():
        m = Mock(name, port)
        server = uvicorn.Server(uvicorn.Config(m.app, host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        mocks[name] = m
    time.sleep(1.5)
    return mocks
