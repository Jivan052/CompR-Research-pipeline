"""
deep_research_agent.py

Stage 2 of the pipeline: for every app, research (or confirm) auth method,
self-serve vs gated status, API surface, buildability verdict, and evidence
URL, using an LLM with a real web-search tool, forced into a strict JSON
schema.

Supports two interchangeable backends, chosen automatically from whichever
API key is present in the environment:

  - ANTHROPIC (preferred if ANTHROPIC_API_KEY is set): uses Claude's native
    web_search server tool.
  - OPENROUTER (used if OPENROUTER_API_KEY is set instead): uses OpenRouter's
    `openrouter:web_search` server tool, which works across many
    tool-calling models through one unified API - this is what lets anyone
    who clones this repo run it with whatever model/provider they already
    have credits on, without needing an Anthropic key specifically.

Credentials are read ONLY from environment variables (or a local .env file
via python-dotenv, if present). Never hardcode a key in this file, and never
commit a .env file - see .env.example and .gitignore.

Usage:
    cp .env.example .env          # fill in your own key(s)
    pip install -r requirements.txt
    python agent/deep_research_agent.py

Output:
    data/research_results.json  (resumable - safe to Ctrl+C and re-run)
"""

import json
import os
import sys
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional; env vars can be set directly instead

DATA = Path(__file__).parent.parent / "data"
LOGS = Path(__file__).parent.parent / "logs"
APPS_FILE = DATA / "apps_100.json"
COMPOSIO_MATCHES = DATA / "composio_toolkit_matches.json"
OUT_FILE = DATA / "research_results.json"
LOG_FILE = LOGS / "deep_research_run.jsonl"

LOGS.mkdir(exist_ok=True)


def log_call(app_name, backend, model, request_meta, response_meta, elapsed_s, ok, error=None):
    """Append one JSONL record per API call - this is the audit trail.
    Each line is proof of an actual outbound call: real timestamp, real
    latency, and (for OpenRouter) the response's request id, which you can
    cross-check against your own OpenRouter/Anthropic usage dashboard."""
    import datetime
    record = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "app": app_name,
        "backend": backend,
        "model": model,
        "elapsed_seconds": round(elapsed_s, 2),
        "ok": ok,
        "request": request_meta,
        "response_meta": response_meta,
        "error": error,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")


# Default models. Override via env vars if you want a different one.
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5")

SYSTEM_PROMPT = """You are an API/toolkit research agent. For the given app, use \
web search to find its developer documentation and answer with ONLY a JSON \
object (no prose, no markdown fences) with these exact keys:

{
  "category": "one of: CRM and Sales, Support and Helpdesk, Communications and \
Messaging, Marketing Ads Email Social, Ecommerce, Data SEO Scraping, \
Dev Infra Data platforms, Productivity and PM, Finance and Fintech, AI Research Media",
  "one_liner": "what the product does, under 15 words",
  "auth": ["OAuth2" | "API key" | "Basic" | "Token" | "Other", ...],
  "self_serve": true | false,
  "gating": "short note: free/trial self-serve, or what gate exists (paid plan, admin approval, partner/contact-sales)",
  "api_surface": "short note: REST/GraphQL, roughly how broad, and whether an MCP server exists",
  "existing_mcp": true | false,
  "verdict": "Ready today" | "Ready with friction" | "Blocked",
  "blocker": "main blocker if not fully ready, else null",
  "evidence": "the specific docs URL you found this on",
  "confidence": "high" | "medium" | "low"
}

Base every field on what you actually find via web search - do not guess. \
If docs are unreachable or contradictory, set confidence to low and say why \
in the gating field. Only output the JSON object, nothing else."""


def research_with_anthropic(app: dict) -> dict:
    import anthropic
    import time as _time
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    t0 = _time.time()
    try:
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=[{"role": "user", "content": f"App: {app['name']}\nHint: {app.get('hint','')}"}],
        )
    except Exception as e:
        log_call(app["name"], "anthropic", ANTHROPIC_MODEL, {"prompt_app": app["name"]},
                  None, _time.time() - t0, ok=False, error=str(e))
        raise
    elapsed = _time.time() - t0
    # count how many actual web_search tool-use blocks the model made -
    # a real proof it searched, not just recalled from memory
    search_calls = sum(1 for b in resp.content if getattr(b, "type", None) == "server_tool_use")
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    log_call(
        app["name"], "anthropic", ANTHROPIC_MODEL,
        {"prompt_app": app["name"]},
        {"response_id": resp.id, "stop_reason": resp.stop_reason,
         "web_search_calls_made": search_calls, "output_tokens": resp.usage.output_tokens},
        elapsed, ok=True,
    )
    return _parse_json(text)


def research_with_openrouter(app: dict) -> dict:
    import requests
    import time as _time
    api_key = os.environ["OPENROUTER_API_KEY"]
    t0 = _time.time()
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": OPENROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"App: {app['name']}\nHint: {app.get('hint','')}"},
                ],
                # OpenRouter's model-driven web search server tool - works across
                # any tool-calling model on the platform, not just one provider.
                "tools": [{"type": "openrouter:web_search"}],
            },
            timeout=90,
        )
        resp.raise_for_status()
    except Exception as e:
        log_call(app["name"], "openrouter", OPENROUTER_MODEL, {"prompt_app": app["name"]},
                  None, _time.time() - t0, ok=False, error=str(e))
        raise
    elapsed = _time.time() - t0
    payload = resp.json()
    text = payload["choices"][0]["message"]["content"].strip()
    # payload["id"] is OpenRouter's own request id - look it up in your
    # OpenRouter Activity dashboard (openrouter.ai/activity) to independently
    # confirm this exact call happened.
    log_call(
        app["name"], "openrouter", OPENROUTER_MODEL,
        {"prompt_app": app["name"]},
        {"openrouter_request_id": payload.get("id"), "usage": payload.get("usage")},
        elapsed, ok=True,
    )
    return _parse_json(text)


def _parse_json(text: str) -> dict:
    text = text.strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"parse_error": True, "raw": text}


def pick_backend():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return research_with_anthropic, "anthropic"
    if os.environ.get("OPENROUTER_API_KEY"):
        return research_with_openrouter, "openrouter"
    sys.exit(
        "No API key found. Set ANTHROPIC_API_KEY or OPENROUTER_API_KEY "
        "in your environment (or in a local .env file - see .env.example)."
    )


def main():
    research_fn, backend = pick_backend()
    print(f"Using backend: {backend}")

    apps = json.loads(APPS_FILE.read_text())
    composio_matches = {}
    if COMPOSIO_MATCHES.exists():
        composio_matches = json.loads(COMPOSIO_MATCHES.read_text())

    results = {}
    if OUT_FILE.exists():
        try:
            results = json.loads(OUT_FILE.read_text())
        except json.JSONDecodeError:
            results = {}

    for app in apps:
        name = app["name"]
        if name in results and not results[name].get("parse_error"):
            continue
        print(f"Researching {name}...")
        try:
            r = research_fn(app)
        except Exception as e:
            print(f"  error: {e}")
            r = {"error": str(e)}
        r["composio_toolkit"] = composio_matches.get(name, {"exists_in_composio": None})
        results[name] = r
        OUT_FILE.write_text(json.dumps(results, indent=2))  # save after every app
        time.sleep(0.5)

    print(f"\nDone. Wrote {len(results)} results to {OUT_FILE}")
    print(f"Audit log (one line per real API call, with timestamps and provider request IDs): {LOG_FILE}")
    if LOG_FILE.exists():
        lines = LOG_FILE.read_text().strip().splitlines()
        oks = sum(1 for l in lines if json.loads(l)["ok"])
        print(f"  {len(lines)} calls logged this session, {oks} succeeded. "
              f"Open the file or run: python -c \"import json; [print(json.loads(l)['timestamp'], json.loads(l)['app'], json.loads(l)['response_meta']) for l in open('{LOG_FILE}')]\"")


if __name__ == "__main__":
    main()
