"""
composio_toolkit_check.py

Step 1 of the research agent: for each of the 100 apps, ask Composio's own
platform (via the composio SDK) whether a toolkit already exists for it,
and if so, pull its real auth scheme(s), tool count, and category.

This uses the actual `composio` Python SDK (pip install composio) against
the live Composio API. Requires COMPOSIO_API_KEY in the environment.

Run:
    export COMPOSIO_API_KEY=your_key_here
    python agent/composio_toolkit_check.py

Output:
    data/composio_toolkit_matches.json
"""

import json
import os
import time
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional; env vars can be set directly instead

from composio import Composio

APPS_FILE = Path(__file__).parent.parent / "data" / "apps_100.json"
OUT_FILE = Path(__file__).parent.parent / "data" / "composio_toolkit_matches.json"
LOGS = Path(__file__).parent.parent / "logs"
LOG_FILE = LOGS / "composio_check_run.jsonl"
LOGS.mkdir(exist_ok=True)


def log_call(app_name, slugs_tried, found_slug, ok, elapsed_s, error=None):
    import datetime
    record = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "app": app_name,
        "slugs_tried": slugs_tried,
        "matched_slug": found_slug,
        "elapsed_seconds": round(elapsed_s, 2),
        "ok": ok,
        "error": error,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")

# Candidate slugs to try per app (Composio toolkit slugs are usually
# lowercase, no spaces, sometimes abbreviated). We try a few guesses
# per app since slugs aren't always the obvious name.
def slug_candidates(app_name: str) -> list[str]:
    base = app_name.lower().strip()
    candidates = {base}
    candidates.add(base.replace(" ", "_"))
    candidates.add(base.replace(" ", "-"))
    candidates.add(base.replace(" ", ""))
    # common aliasing rules seen in composio's catalog
    aliases = {
        "google ads": "googleads",
        "meta ads": "facebook_ads",
        "linkedin ads": "linkedin",
        "amazon selling partner": "amazon_seller",
        "whatsapp business": "whatsapp",
        "youtube transcript": "youtube",
        "salesforce commerce cloud": "salesforce",
        "magento (adobe commerce)": "magento",
        "notebooklm": "google_notebooklm",
        "meta ads": "facebook_ads",
    }
    if base in aliases:
        candidates.add(aliases[base])
    return list(candidates)


def main():
    api_key = os.environ.get("COMPOSIO_API_KEY")
    if not api_key:
        raise SystemExit("Set COMPOSIO_API_KEY in your environment first.")

    client = Composio(api_key=api_key)
    apps = json.loads(APPS_FILE.read_text())

    results = {}
    for app in apps:
        name = app["name"]
        found = None
        slugs = slug_candidates(name)
        t0 = time.time()
        error = None
        for slug in slugs:
            try:
                info = client.toolkits.get(slug)
                found = {
                    "slug": slug,
                    "exists_in_composio": True,
                    "auth_schemes": [
                        d.mode for d in (info.auth_config_details or [])
                    ],
                    "category": getattr(info, "category", None),
                    "tool_count": len(getattr(info, "tools", []) or []),
                }
                break
            except Exception as e:
                error = str(e)
                continue
        if found is None:
            found = {"exists_in_composio": False}
        results[name] = found
        log_call(name, slugs, found.get("slug"), ok=True, elapsed_s=time.time() - t0,
                 error=None if found.get("exists_in_composio") else error)
        time.sleep(0.2)  # be polite to the API
        print(f"{name}: {found.get('exists_in_composio')}")

    OUT_FILE.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {OUT_FILE}")
    print(f"Audit log (real API call per app, with timestamps): {LOG_FILE}")


if __name__ == "__main__":
    main()
