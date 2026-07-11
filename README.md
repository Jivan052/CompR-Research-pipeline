# CompR: Realtime research pipeline — 100 Apps

Research pipeline + case study for the AI Product Ops take-home. Audits 100 apps across
10 categories for auth method, self-serve vs gated credentials, API surface, MCP status,
and a buildability verdict — then verifies the results in two rounds against live docs.

**Case study:** open `site/index.html` directly in a browser, or deploy it (steps below).

## Repo layout

```
agent/
  composio_toolkit_check.py   # Stage 1: real Composio SDK — checks which apps already
                               # exist as Composio toolkits, pulls their real auth schemes
  deep_research_agent.py      # Stage 2: LLM + live web search, structured JSON per app.
                               # Auto-selects Anthropic or OpenRouter as backend.
data/
  apps_100.json                 # the 100-app input list
  research_results.json         # the merged, twice-verified dataset (100 rows)
  pattern_analysis.json         # aggregated stats (auth mix, self-serve rate, category matrix)
  composio_toolkit_matches.json # (produced by Stage 1 when run live)
verification/
  verification_log.json         # two-round verification methodology, hits/misses, accuracy
site/
  index.html                    # the single-page case study (self-contained, data embedded)
  data_embed.json               # the exact array embedded into index.html
run_pipeline.py                 # orchestrator: runs both stages, recomputes stats, rebuilds site
requirements.txt
.env.example                    # copy to .env and fill in your own keys — never commit .env
.gitignore                      # .env is ignored by default
```

## Setup (5 minutes)

```bash
git clone <repo-url>
cd composio-research
python3 -m venv .venv && source .venv/bin/activate    # optional but recommended
pip install -r requirements.txt

cp .env.example .env
# open .env and fill in:
#   COMPOSIO_API_KEY=...          (for Stage 1)
#   ANTHROPIC_API_KEY=...         (for Stage 2, OR)
#   OPENROUTER_API_KEY=...        (for Stage 2, if you don't have an Anthropic key)
```

## Run the full pipeline

```bash
python run_pipeline.py
```

This runs, in order:
1. `agent/composio_toolkit_check.py` — real calls to the Composio API via the [Composio](https://composio.dev)
2. `agent/deep_research_agent.py` — real web-search-grounded research per app, resumable
   (safe to Ctrl+C and re-run; it skips apps already in `data/research_results.json`)
3. Recomputes `data/pattern_analysis.json` from the fresh results
4. Re-embeds the data into `site/index.html` so the case study reflects the new run

Each stage can also be run individually — see the scripts' own docstrings.

### Why two backends for Stage 2?

`deep_research_agent.py` picks its backend automatically:
- If `ANTHROPIC_API_KEY` is set, it uses Claude directly with Claude's native
  `web_search` server tool.
- Otherwise, if `OPENROUTER_API_KEY` is set, it uses OpenRouter's
  `openrouter:web_search` server tool, which works the same way across many
  different tool-calling models through one unified API. (Refer [Openrouter](https://openrouter.ai/)]

This means anyone cloning the repo can run it with whatever provider they already have
credits on — no dependency on one specific vendor's key.

## Verification methodology (see `verification/verification_log.json` for full detail)

Two rounds, not one:

1. **Round 1** — a random sample of 15/100 apps (seed=42) spot-checked against live docs.
   Found 1 error (Reducto's MCP status was stale) → corrected. 15/16 fields correct
   before the fix, 16/16 after.
2. **Round 2** — every app the agent had flagged **low confidence** (8 apps) was
   independently re-researched against live docs, regardless of the random sample, since
   those are the highest-risk rows. 6 of those 8 were corrected or confidence-upgraded to
   high/medium. 2 (Pumble, Paygent Connect) remain honestly flagged low-confidence —
   thin/contradictory public docs even on a second pass.

**Final state:** 70 apps at high confidence, 28 at medium, 2 at low — reported exactly
as that, not smoothed into a false "100% verified" claim.

## Known limitations / where a human is still needed

- Composio toolkit slug-guessing (Stage 1) uses a small hand-maintained alias table
  (`slug_candidates()` in `composio_toolkit_check.py`) that will drift as Composio adds
  toolkits — needs periodic review, not just a wider regex.
- "Self-serve" vs "gated" sometimes required a judgment call between conflicting signals
  on a vendor's marketing page vs. their actual docs page (fanbasis, Magento, Pinterest).
- Name collisions are a real failure mode: "iPayX" first returned an unrelated generic
  "iPay" payment gateway before a targeted re-search found the actual FX-audit product.
- Pumble and Paygent Connect genuinely defeated two research passes — reported as such.

## How to verify a run actually happened (not simulated)

Every run of either stage writes a real audit log to `logs/` — one JSON line per
API call, with a timestamp, latency, and the **provider's own request ID**:

- `logs/composio_check_run.jsonl` — one line per app, which slugs were tried, whether
  a real Composio toolkit match was found.
- `logs/deep_research_run.jsonl` — one line per app, including:
  - `response_meta.response_id` (Anthropic) or `response_meta.openrouter_request_id`
    (OpenRouter) — look this ID up in your provider's own dashboard
    (console.anthropic.com or openrouter.ai/activity) to independently confirm, from
    a source I have no control over, that the call actually happened.
  - `response_meta.web_search_calls_made` (Anthropic backend) — how many times the
    model actually invoked the search tool for that app, proving it searched rather
    than answered from memory.
  - `elapsed_seconds` — real per-call latency (a hardcoded/simulated response
    wouldn't have this variance; live web-search-grounded calls typically take
    3-15 seconds each due to the search round-trip).

After a run, spot-check a few rows against your own dashboard:
```bash
tail -5 logs/deep_research_run.jsonl | python3 -m json.tool
```
Then compare the request ID and timestamp shown against your provider's usage/activity
log for that same window. If they match, the run was real.

## Regenerating just the site (without re-running the research)

If you hand-edit `data/research_results.json` and want to refresh the page without
re-running the agents:

```bash
python3 -c "
import json, re
data = json.load(open('data/research_results.json'))
rows = data.values() if isinstance(data, dict) else data
compact = [[d['name'], d['category'], d['one_liner'], d['auth'], d['self_serve'],
            d['gating'], d['api_surface'], d['existing_mcp'], d['verdict'],
            d['blocker'], d['evidence'], d['confidence']] for d in rows]
json.dump(compact, open('site/data_embed.json','w'))
html = open('site/index.html').read()
html = re.sub(r'const DATA = \[.*?\];\n// columns', f'const DATA = {json.dumps(compact)};\n// columns', html, flags=re.S)
open('site/index.html','w').write(html)
"
```

(`run_pipeline.py` does this automatically as its final step.)

# Hope you will like it! visit - https://composio.dev/ for more info
