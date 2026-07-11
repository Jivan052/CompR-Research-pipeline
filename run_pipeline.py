#!/usr/bin/env python3
"""
run_pipeline.py

Runs the full pipeline end to end:
  1. Composio toolkit check (skipped with a warning if COMPOSIO_API_KEY is unset)
  2. Deep research agent (Anthropic or OpenRouter, whichever key is present)
  3. Recompute pattern_analysis.json from the results
  4. Re-embed data/research_results.json into site/index.html

Run from the repo root:
    python run_pipeline.py
"""
import json
import subprocess
import sys
import re
from pathlib import Path
from collections import Counter, defaultdict

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import os

ROOT = Path(__file__).parent
DATA = ROOT / "data"


def step(msg):
    print(f"\n{'='*60}\n{msg}\n{'='*60}")


def run_composio_check():
    step("Stage 1: Composio toolkit check")
    if not os.environ.get("COMPOSIO_API_KEY"):
        print("COMPOSIO_API_KEY not set - skipping. Stage 2 will still run "
              "without Composio cross-reference data.")
        return
    subprocess.run([sys.executable, str(ROOT / "agent" / "composio_toolkit_check.py")], check=True)


def run_deep_research():
    step("Stage 2: Deep research agent")
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENROUTER_API_KEY")):
        print("Neither ANTHROPIC_API_KEY nor OPENROUTER_API_KEY is set. "
              "Cannot run Stage 2. Set one in your .env file and re-run.")
        sys.exit(1)
    subprocess.run([sys.executable, str(ROOT / "agent" / "deep_research_agent.py")], check=True)


def recompute_patterns():
    step("Stage 3: Recomputing pattern analysis")
    data = json.loads((DATA / "research_results.json").read_text())

    def normalize(auths):
        auths = auths or []
        tags = []
        if any('OAuth2' in a for a in auths): tags.append('OAuth2')
        if any('API key' in a or 'API token' in a or 'token' in a.lower() for a in auths): tags.append('API key/token')
        if any('Basic' in a for a in auths): tags.append('Basic')
        return tags

    combo = Counter()
    self_serve = Counter()
    verdict = Counter()
    mcp = Counter()
    conf = Counter()
    cat_stats = defaultdict(lambda: {'total': 0, 'self_serve': 0, 'ready': 0, 'mcp': 0})

    for d in data.values() if isinstance(data, dict) else data:
        auth = d.get('auth', [])
        combo[tuple(sorted(normalize(auth)))] += 1
        self_serve[str(d.get('self_serve'))] += 1
        verdict[d.get('verdict', 'unknown')] += 1
        mcp[str(d.get('existing_mcp'))] += 1
        conf[d.get('confidence', 'unknown')] += 1
        cat = d.get('category', 'unknown')
        cat_stats[cat]['total'] += 1
        if d.get('self_serve'): cat_stats[cat]['self_serve'] += 1
        if d.get('verdict') == 'Ready today': cat_stats[cat]['ready'] += 1
        if d.get('existing_mcp'): cat_stats[cat]['mcp'] += 1

    out = {
        'auth_combos': {' + '.join(k) if k else 'none': v for k, v in combo.items()},
        'self_serve': dict(self_serve),
        'verdict': dict(verdict),
        'mcp': dict(mcp),
        'confidence': dict(conf),
        'category_stats': {k: dict(v) for k, v in cat_stats.items()},
    }
    (DATA / "pattern_analysis.json").write_text(json.dumps(out, indent=2))
    print(f"Wrote {DATA / 'pattern_analysis.json'}")


def rebuild_site():
    step("Stage 4: Re-embedding data into site/index.html")
    data = json.loads((DATA / "research_results.json").read_text())
    rows = data.values() if isinstance(data, dict) else data
    compact = [
        [d.get('name'), d.get('category'), d.get('one_liner'), d.get('auth', []),
         d.get('self_serve'), d.get('gating'), d.get('api_surface'),
         d.get('existing_mcp'), d.get('verdict'), d.get('blocker'),
         d.get('evidence'), d.get('confidence')]
        for d in rows
    ]
    embed_path = ROOT / "site" / "data_embed.json"
    embed_path.write_text(json.dumps(compact))

    html_path = ROOT / "site" / "index.html"
    html = html_path.read_text()
    new_data = json.dumps(compact)
    html = re.sub(r"const DATA = \[.*?\];\n// columns", f"const DATA = {new_data};\n// columns", html, flags=re.S)
    html_path.write_text(html)
    print(f"Re-embedded {len(compact)} rows into {html_path}")


if __name__ == "__main__":
    run_composio_check()
    run_deep_research()
    recompute_patterns()
    rebuild_site()
    step("Pipeline complete. Open site/index.html to view the case study.")
