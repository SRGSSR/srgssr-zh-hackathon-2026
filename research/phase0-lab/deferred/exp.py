import subprocess, time, httpx, yaml, os
from mock_openai import start_mocks
M = start_mocks({"ch": 9301})
M["ch"].mode = "down"
cfg = {"model_list": [{"model_name": "apertus", "litellm_params": {"model": "openai/x", "api_base": "http://127.0.0.1:9301/v1", "api_key": "k"}}],
       "litellm_settings": {"callbacks": ["deferred_plugin.plugin"]}, "general_settings": {"master_key": "sk-m"},
       "router_settings": {"num_retries": 0, "disable_cooldowns": True}}
yaml.safe_dump(cfg, open("/lab/deferred/cfg.yaml", "w"))
p = subprocess.Popen(["litellm", "--config", "/lab/deferred/cfg.yaml", "--port", "4000"], cwd="/lab/deferred",
                     env={**os.environ, "PYTHONPATH": "/lab/deferred:/lab"}, stdout=open("/tmp/p.log", "w"), stderr=subprocess.STDOUT)
for _ in range(90):
    try:
        if httpx.get("http://127.0.0.1:4000/health/liveliness", timeout=1).status_code == 200: break
    except Exception: time.sleep(1)
H = {"Authorization": "Bearer sk-m"}
r = httpx.post("http://127.0.0.1:4000/v1/deferred/chat/completions", headers=H, json={"model": "apertus", "messages": [{"role": "user", "content": "hi"}]})
print("submit", r.status_code, r.text)
jid = r.json().get("id")
time.sleep(3); print("while down:", httpx.get(f"http://127.0.0.1:4000/v1/deferred/{jid}", headers=H).json(), "mock count", M["ch"].count)
M["ch"].mode = "up"; time.sleep(2.5)
print("after restore:", httpx.get(f"http://127.0.0.1:4000/v1/deferred/{jid}", headers=H).json())
print("unauth GET status:", httpx.get(f"http://127.0.0.1:4000/v1/deferred/{jid}").status_code)
p.terminate()
