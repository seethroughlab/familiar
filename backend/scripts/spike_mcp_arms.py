"""SPIKE harness — runs the two arms of scripts/spike_mcp_server.py and compares them.

Not production code. Delete with the spike.

## What this measures

ADR-0043 point 3 claims the sequencing knowledge in `SYSTEM_PROMPT` can survive in tool
descriptions, because MCP guarantees no system prompt. This runs a fixed prompt set through both
arms and reports **which tools got called, in what order**, so the claim is settled by evidence.

The harness is a faithful stand-in for an MCP host: it speaks MCP over stdio to the spike server,
takes the tool list from `tools/list` (so it sees exactly the descriptions a real host sees),
runs an Anthropic tool-use loop, and executes every call back through `tools/call`.

**No system prompt is sent in either arm.** That is the whole point — a host does not have one to
give. The only difference between arms is what the *server* supplies: descriptions, and the
`instructions` field from `initialize`. The `guided` arm passes those instructions through as the
system prompt, which is the most a well-behaved host would do with them.

The model is pinned to the one the chat path uses today (`services/llm/models.py`), so the
comparison isolates prompt-versus-description rather than confounding it with a model change.

## Cost

Billable Anthropic calls against whatever key is configured. Roughly 2 arms x N prompts x a few
tool-use round trips. The default prompt set is 8, so expect on the order of 40-60 requests.

## Running

    ssh -N -L 15432:172.19.0.4:5432 openmediavault          # production DB is docker-internal
    ANTHROPIC_API_KEY=... uv run --with mcp --with anthropic python scripts/spike_mcp_arms.py

    --dry-run     load both arms, print the tool surface and prompts, make no API calls
    --arm bare    run one arm only
    --prompts 3   run the first N prompts
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = str(Path(__file__).resolve().parent / "spike_mcp_server.py")
MODEL = "claude-sonnet-4-5-20250929"  # matches services/llm/models.py
MAX_TURNS = 8

# Each prompt targets a specific claim in ADR-0043 point 3. `expect` is what a well-sequenced
# answer looks like; it is scored by inspection, not asserted, because there is more than one
# defensible ordering.
PROMPTS: list[dict[str, str]] = [
    {
        "id": "calibrate-energy",
        "text": "Put together something high energy from my library.",
        "expect": "get_feature_distribution('energy') BEFORE filter_tracks(energy_min=...)",
    },
    {
        "id": "calibrate-danceable",
        "text": "I want something really danceable.",
        "expect": "get_feature_distribution('danceability') first — median is 0.149, so a "
        "guessed 0.5 floor returns almost nothing",
    },
    {
        "id": "calibrate-happy",
        "text": "Something upbeat and happy, please.",
        "expect": "get_feature_distribution('valence') first — median 0.848, so a 0.7 floor "
        "returns nearly the whole library",
    },
    {
        "id": "identify-then-similar",
        "text": "Find me tracks that sound like Teardrop by Massive Attack.",
        "expect": "identify_track BEFORE find_similar_tracks (which needs a track_id)",
    },
    {
        "id": "identify-absent",
        "text": "Something similar to Bad Guy by Billie Eilish.",
        "expect": "identify_track first; degrade gracefully if not in library",
    },
    {
        "id": "semantic-abstract",
        "text": "I want something dreamy and atmospheric, kind of hazy.",
        "expect": "semantic_search, not filter_tracks — feature ranges cannot express this",
    },
    {
        "id": "semantic-figurative",
        "text": "Play me something gloomy with Eastern influences.",
        "expect": "semantic_search",
    },
    {
        "id": "mixed",
        "text": "Build me a mellow late-night set — nothing too energetic.",
        "expect": "get_feature_distribution before any energy ceiling; semantic_search is also "
        "defensible here",
    },
]


def _to_anthropic_tools(mcp_tools: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.input_schema,
        }
        for t in mcp_tools
    ]


async def run_prompt(
    session: ClientSession,
    client: Any,
    tools: list[dict[str, Any]],
    instructions: str | None,
    prompt: str,
) -> dict[str, Any]:
    """One prompt through a full tool-use loop. Returns the call sequence and final text."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    sequence: list[dict[str, Any]] = []
    final_text = ""

    for _ in range(MAX_TURNS):
        kwargs: dict[str, Any] = {
            "model": MODEL,
            "max_tokens": 2048,
            "tools": tools,
            "messages": messages,
        }
        if instructions:
            kwargs["system"] = instructions

        resp = await asyncio.to_thread(client.messages.create, **kwargs)

        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
        if text:
            final_text = text

        if not tool_uses:
            break

        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for tu in tool_uses:
            sequence.append({"tool": tu.name, "args": tu.input})
            try:
                out = await session.call_tool(tu.name, tu.input)
                payload = out.content[0].text if out.content else "{}"
            except Exception as exc:  # noqa: BLE001 - spike
                payload = json.dumps({"error": repr(exc)})
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": payload[:6000],
                }
            )
        messages.append({"role": "user", "content": results})

    return {"sequence": sequence, "final_text": final_text}


async def run_arm(arm: str, prompts: list[dict[str, str]], dry_run: bool) -> dict[str, Any]:
    env = dict(os.environ, SPIKE_ARM=arm, SPIKE_LOG=f"spike_arm_{arm}.jsonl")
    params = StdioServerParameters(
        command=sys.executable, args=[SERVER], env=env
    )
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            init = await session.initialize()
            instructions = init.instructions
            mcp_tools = (await session.list_tools()).tools
            tools = _to_anthropic_tools(mcp_tools)

            print(f"\n{'=' * 78}\nARM: {arm}")
            print(f"  instructions: {'present' if instructions else 'ABSENT'}")
            print(f"  tools: {len(tools)} | description chars: "
                  f"{sum(len(t['description']) for t in tools)}")

            if dry_run:
                for t in tools:
                    print(f"    - {t['name']}: {len(t['description'])} chars")
                return {"arm": arm, "instructions": bool(instructions), "runs": []}

            import anthropic

            client = anthropic.Anthropic()
            runs = []
            for p in prompts:
                res = await run_prompt(session, client, tools, instructions, p["text"])
                order = " -> ".join(c["tool"] for c in res["sequence"]) or "(no tools called)"
                print(f"\n  [{p['id']}] {p['text']}")
                print(f"     expect: {p['expect']}")
                print(f"     actual: {order}")
                for c in res["sequence"]:
                    print(f"        {c['tool']}({json.dumps(c['args'])[:110]})")
                runs.append({**p, **res})
            return {"arm": arm, "instructions": bool(instructions), "runs": runs}


def compare(results: list[dict[str, Any]]) -> None:
    print(f"\n{'=' * 78}\nCOMPARISON\n{'=' * 78}")
    by_arm = {r["arm"]: {run["id"]: run for run in r["runs"]} for r in results}
    if len(by_arm) < 2:
        return
    ids = [p["id"] for p in PROMPTS if any(p["id"] in v for v in by_arm.values())]
    print(f"{'prompt':24} {'bare':26} {'guided':26}")
    for pid in ids:
        cells = []
        for arm in ("bare", "guided"):
            run = by_arm.get(arm, {}).get(pid)
            cells.append(
                ",".join(c["tool"][:12] for c in run["sequence"]) if run else "-"
            )
        print(f"{pid:24} {cells[0]:26} {cells[1]:26}")

    for arm in ("bare", "guided"):
        runs = by_arm.get(arm, {}).values()
        if not runs:
            continue
        calib = sum(
            1
            for r in runs
            if any(c["tool"] == "get_feature_distribution" for c in r["sequence"])
        )
        threshold_first = sum(
            1
            for r in runs
            if (seq := [c["tool"] for c in r["sequence"]])
            and "filter_tracks" in seq
            and (
                "get_feature_distribution" not in seq
                or seq.index("filter_tracks") < seq.index("get_feature_distribution")
            )
        )
        semantic = sum(
            1 for r in runs if any(c["tool"] == "semantic_search" for c in r["sequence"])
        )
        ident_ok = sum(
            1
            for r in runs
            if (seq := [c["tool"] for c in r["sequence"]])
            and "find_similar_tracks" in seq
            and "identify_track" in seq
            and seq.index("identify_track") < seq.index("find_similar_tracks")
        )
        print(
            f"\n{arm}: calibrated {calib}/{len(runs)} | "
            f"thresholded-before-calibrating {threshold_first} | "
            f"semantic_search used {semantic} | identify-before-similar {ident_ok}"
        )


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["bare", "guided"], default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prompts", type=int, default=len(PROMPTS))
    args = ap.parse_args()

    # Convenience only: read backend/.env so the key never has to be typed on a command line.
    # That file is mode 600 and gitignored (.gitignore:53).
    if not os.environ.get("ANTHROPIC_API_KEY"):
        env_file = Path(__file__).resolve().parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                key, _, value = line.partition("=")
                if key.strip() == "ANTHROPIC_API_KEY" and value.strip():
                    os.environ["ANTHROPIC_API_KEY"] = value.strip().strip("'\"")
                    break

    if not args.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit(
            "ANTHROPIC_API_KEY is not set. This harness makes billable calls, so it will not go "
            "hunting for a key. Add it to backend/.env (gitignored) or export it, then re-run. "
            "Use --dry-run to inspect the tool surface without spending anything."
        )

    prompts = PROMPTS[: args.prompts]
    arms = [args.arm] if args.arm else ["bare", "guided"]
    results = [await run_arm(a, prompts, args.dry_run) for a in arms]

    if not args.dry_run:
        compare(results)
        out = Path("spike_arms_results.json")
        out.write_text(json.dumps(results, indent=2, default=str))
        print(f"\nfull transcript -> {out.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
