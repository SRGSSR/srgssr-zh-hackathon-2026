"""Optional: run questions through a real MCP client + LLM (Claude Code headless) connected only to this server.

Requires the `claude` CLI (logged in). Each question costs roughly USD 0.05-0.25. Web search/fetch and local tools are
disabled so the model can only use this server. Prints the tools called, time, cost and the answer.

    uv run python tests/llm_client_eval.py              # the five published sample questions + two edge cases
    uv run python tests/llm_client_eval.py "Question?"  # custom question(s)
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = [
    "Wann wird bei uns das nächste Mal Karton abgeholt?",
    "Comment puis-je échanger mon permis de conduire étranger contre un permis suisse dans le canton de Vaud, "
    "et combien de temps ai-je pour le faire?",
    "Qual è il premio mensile più basso dell'assicurazione di base per un adulto di 30 anni domiciliato a Lugano "
    "con franchigia di 2500 franchi?",
    "Cura èn las vacanzas d'atun 2026 per la scola da Scuol?",
    "Wie hoch ist der Rundfunkbeitrag, den ich nach meinem Umzug nach Konstanz zahlen muss?",
    "Wie hoch ist die günstigste Krankenkassenprämie in Wil für 40-Jährige mit Franchise 300?",
    "Qual è il tasso ipotecario di riferimento attualmente in vigore per gli affitti in Svizzera?",
]


def ask(question: str, config: Path) -> dict:
    t0 = time.time()
    p = subprocess.run(
        ["claude", "-p", "--mcp-config", str(config), "--strict-mcp-config",
         "--allowedTools", "mcp__swiss-grounding__*",
         "--disallowedTools", "Bash,Edit,Write,Read,WebFetch,WebSearch,Glob,Grep,Agent,Task",
         "--output-format", "stream-json", "--verbose", question],
        capture_output=True, text=True, timeout=300, cwd=config.parent)
    tools, answer, cost = [], "", None
    for line in p.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            tools += [c["name"].removeprefix("mcp__swiss-grounding__")
                      for c in ev["message"].get("content", []) if c.get("type") == "tool_use"]
        elif ev.get("type") == "result":
            answer, cost = ev.get("result", ""), ev.get("total_cost_usd")
    return {"question": question, "tools": [t for t in tools if t != "ToolSearch"], "seconds": round(time.time() - t0),
            "cost_usd": round(cost, 3) if cost else None, "answer": answer}


def main() -> None:
    questions = sys.argv[1:] or QUESTIONS
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "mcp.json"
        config.write_text(json.dumps({"mcpServers": {"swiss-grounding": {
            "command": "uv", "args": ["run", "--directory", str(ROOT), "swiss-grounding-mcp"]}}}))
        for q in questions:
            r = ask(q, config)
            print(f"### {q}\ntools={r['tools']} {r['seconds']}s ${r['cost_usd']}\n{r['answer']}\n", flush=True)


if __name__ == "__main__":
    main()
