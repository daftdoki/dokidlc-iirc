#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6"]
# ///
"""Replay judged prompts through `claude -p` with a given recall line, and count the pages the model reads.

  scripts/line-replay.py --replay FILE [--variants today,...] [--sample N] [--seed S] [--passed FILE] [--streams DIR] [--dry-run] [--out FILE]

FILE is a replay JSONL file, one judged pair per line:
{"repo", "qid", "prompt", "via", "page", "label"}. Only `via: prompt` rows are
replayed, since a failure recall has no prompt a person typed. --sample N takes N
prompts with a relevant page and N without, chosen with --seed.

For each prompt the passed pages come from bin/iirc's hybrid_search and
recall_verdicts in the replay's repo, or from --passed FILE when it exists (the
script writes it when it does not, so a dry run and the real run show the same
pages). A variant turns those pages into the line a UserPromptSubmit hook prints.

Each run: XDG_STATE_HOME is a temporary directory, so its log rows never reach
the real log; IIRC_RECORDING=1; the iirc plugin is disabled through --settings,
so its own recall hook stays silent; this checkout's bin/ is first on PATH, so
`iirc read` still runs. The model may run only `iirc read`, `iirc pull`, and
`iirc search` in Bash, plus Read, Grep, and Glob: the prompts are real tasks and
the run's cwd is a real checkout.
"""
import argparse
import importlib.util
import json
import os
import random
import re
import shlex
import subprocess
import sys
import tempfile
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
DISABLE = {"iirc@iirc-dev": False, "iirc@dokidlc": False}
TOOLS = "Bash,Read,Grep,Glob"
ALLOWED = ["Bash(iirc read:*)", "Bash(iirc pull:*)", "Bash(iirc search:*)"]
SEPARATORS_RE = re.compile(r"&&|\|\||[;|\n]")

_IIRC = None


def iirc():
    """bin/iirc as a module, loaded on first use so the counting functions need neither ollama nor a store."""
    global _IIRC
    if _IIRC is None:
        loader = SourceFileLoader("iirc", str(HERE / "bin" / "iirc"))
        spec = importlib.util.spec_from_loader("iirc", loader)
        _IIRC = importlib.util.module_from_spec(spec)
        loader.exec_module(_IIRC)
    return _IIRC


# --- the replay file ---------------------------------------------------------


def load_replay(path: Path) -> dict[tuple[str, str], dict]:
    """Prompts keyed by (repo, qid), each with its text, its via, and its labels by page."""
    out: dict[tuple[str, str], dict] = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        p = out.setdefault((r["repo"], r["qid"]), {"repo": r["repo"], "qid": r["qid"], "prompt": r["prompt"], "via": r.get("via", "prompt"), "labels": {}})
        p["labels"][r["page"]] = r["label"]
    return out


def sample(prompts: dict[tuple[str, str], dict], n: int | None, seed: int) -> list[dict]:
    """N human prompts with a relevant page and N without; all of them when n is None."""
    human = [prompts[k] for k in sorted(prompts) if prompts[k]["via"] == "prompt"]
    if n is None:
        return human
    rng = random.Random(seed)
    with_rel = [p for p in human if "relevant" in p["labels"].values()]
    without = [p for p in human if "relevant" not in p["labels"].values()]
    return rng.sample(with_rel, min(n, len(with_rel))) + rng.sample(without, min(n, len(without)))


# --- the pages a prompt passes -------------------------------------------------


def passed_pages(repo: str, prompt: str) -> list[dict]:
    """The pages today's search and gate pass for this prompt in this repo, best first: {page, store, summary, distance, rule}."""
    m = iirc()
    m.set_root(Path(repo))
    return [{"page": r["filename"], "store": m.row_store(r), "summary": r.get("summary", ""), "distance": r.get("distance"), "rule": r["rule"]}
            for r in m.recall_verdicts(m.hybrid_search(prompt)) if r["verdict"] == "passed"]


def page_rows(prompts: list[dict], cache: Path | None) -> dict[str, list[dict]]:
    """Passed pages by qid, read from the cache file when it exists, else computed and written to it."""
    if cache and cache.is_file():
        return json.loads(cache.read_text())
    rows = {p["qid"]: passed_pages(p["repo"], p["prompt"]) for p in prompts}
    if cache:
        cache.write_text(json.dumps(rows, indent=1))
    return rows


# --- line variants: each builds the hook's line from a prompt's passed pages ------


def today(rows: list[dict]) -> str:
    """The line bin/iirc prints now, suspicion markers read from the pages as the hook reads them."""
    return iirc().recall_line([{**r, "filename": r["page"]} for r in rows])


def proposed(rows: list[dict]) -> str:
    """The next line to compare against today's. Steps 11 and 12 of the search-quality plan write it."""
    raise NotImplementedError("the proposed variant is not written yet")


VARIANTS = {"today": today, "proposed": proposed}


# --- counting reads in a stream-json transcript --------------------------------


def bash_commands(stream: str) -> list[str]:
    """Every Bash command the model ran, in order, from `claude -p --output-format stream-json --verbose` output."""
    out = []
    for line in stream.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or ev.get("type") != "assistant":
            continue
        for block in (ev.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash":
                out.append(str((block.get("input") or {}).get("command", "")))
    return out


def page_name(arg: str) -> str:
    """STORE/PAGE or PAGE, with or without .md, as the bare file name."""
    name = arg.rsplit("/", 1)[-1]
    return name if name.endswith(".md") else name + ".md"


def iirc_calls(command: str) -> list[tuple[str, list[str]]]:
    """(verb, args) for each `iirc read` or `iirc pull` in a shell command, chained ones included."""
    out = []
    for part in SEPARATORS_RE.split(command):
        try:
            toks = shlex.split(part)
        except ValueError:
            toks = part.split()
        for i, t in enumerate(toks[:-1]):
            if t.rsplit("/", 1)[-1] == "iirc" and toks[i + 1] in ("read", "pull"):
                out.append((toks[i + 1], [a for a in toks[i + 2:] if not a.startswith("-")]))
                break
    return out


def count_reads(stream: str, labels: dict[str, str]) -> dict:
    """Reads of relevant, noise, and other pages (unsure or unlabelled), by call, plus pulls that name no labelled page.

    A pull takes a query, not a page; it counts as a read only when the query is a labelled page's name."""
    counts = {"relevant": 0, "noise": 0, "other": 0, "pulls": 0, "pages": {}}
    for command in bash_commands(stream):
        for verb, args in iirc_calls(command):
            if verb == "pull":
                name = page_name(" ".join(args)) if args else ""
                pages = [name] if name in labels else []
                counts["pulls"] += not pages
            else:
                pages = [page_name(a) for a in args]
            for p in pages:
                label = labels.get(p)
                counts[label if label in ("relevant", "noise") else "other"] += 1
                counts["pages"][p] = counts["pages"].get(p, 0) + 1
    return counts


# --- running claude -p -----------------------------------------------------------


def run_once(prompt: dict, line: str, max_turns: int, model: str | None) -> tuple[str, int, float | None]:
    """One headless session in the prompt's repo with this line from the hook; returns its stream, exit code, and cost."""
    with tempfile.TemporaryDirectory(prefix="line-replay-") as tmp:
        t = Path(tmp)
        (t / "line.txt").write_text(line)
        settings = {"enabledPlugins": DISABLE,
                    "hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "cat " + shlex.quote(str(t / "line.txt"))}]}]}}
        (t / "settings.json").write_text(json.dumps(settings))
        env = {**os.environ, "XDG_STATE_HOME": str(t / "state"), "IIRC_RECORDING": "1",
               "PATH": str(HERE / "bin") + os.pathsep + os.environ.get("PATH", "")}
        # the parent session's markers would make this one a child of it, and point iirc at the parent's project
        for var in ("CLAUDE_CODE_CHILD_SESSION", "CLAUDE_PROJECT_DIR", "CLAUDE_CODE_SESSION_ID"):
            env.pop(var, None)
        cmd = ["claude", "-p", prompt["prompt"], "--settings", str(t / "settings.json"), "--output-format", "stream-json", "--verbose",
               "--no-session-persistence", "--permission-mode", "default", "--tools", TOOLS, "--allowedTools", *ALLOWED,
               "--max-turns", str(max_turns)]
        if model:
            cmd += ["--model", model]
        proc = subprocess.run(cmd, cwd=prompt["repo"], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=900)
    cost = None
    for line_ in proc.stdout.splitlines():
        try:
            ev = json.loads(line_)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "result":
            cost = ev.get("total_cost_usd")
    return proc.stdout, proc.returncode, cost


def build_line(variant: str, prompt: dict, rows: list[dict]) -> str | None:
    """The variant's line for this prompt, or None when the variant is a placeholder. Pages resolve in the prompt's repo."""
    iirc().set_root(Path(prompt["repo"]))
    try:
        return VARIANTS[variant](rows)
    except NotImplementedError:
        return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Count the pages a model reads under each recall line variant.")
    ap.add_argument("--replay", required=True, type=Path)
    ap.add_argument("--variants", default="today", help=f"comma-separated, from: {', '.join(VARIANTS)}")
    ap.add_argument("--sample", type=int, help="N prompts with a relevant page and N without; default every human prompt")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--passed", type=Path, help="JSON of passed pages by qid: read when it exists, written when it does not")
    ap.add_argument("--max-turns", type=int, default=8)
    ap.add_argument("--model")
    ap.add_argument("--streams", type=Path, help="directory to keep each run's stream-json output in")
    ap.add_argument("--dry-run", action="store_true", help="print the planned runs and their count, run nothing")
    ap.add_argument("--out", type=Path, help="JSON results: per variant, relevant reads, noise reads, runs")
    args = ap.parse_args(argv)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = [v for v in variants if v not in VARIANTS]
    if unknown:
        ap.error(f"unknown variant {', '.join(unknown)}; known: {', '.join(VARIANTS)}")

    # the search below logs and caches host checks; none of it may reach this machine's real iirc state
    state = tempfile.mkdtemp(prefix="line-replay-state-")
    os.environ["XDG_STATE_HOME"] = state
    prompts = sample(load_replay(args.replay), args.sample, args.seed)
    rows = page_rows(prompts, args.passed)
    plan = []
    for p in prompts:
        for v in variants:
            line = build_line(v, p, rows.get(p["qid"], []))
            plan.append((p, v, line))
    missing = sorted({v for _, v, line in plan if line is None})

    if args.dry_run:
        for p, v, line in plan:
            rel = "relevant" if "relevant" in p["labels"].values() else "none"
            shown = "(variant not written)" if line is None else (line[:160] or "(no line)")
            print(f"{p['qid']}\t{v}\t{rel}\t{shown}")
        print(f"{len(plan)} runs: {len(prompts)} prompts x {len(variants)} variants")
        return 0
    if missing:
        print(f"line-replay: variant {', '.join(missing)} is not written yet", file=sys.stderr)
        return 2

    totals = {v: {"relevant": 0, "noise": 0, "other": 0, "pulls": 0, "runs": 0, "cost_usd": 0.0} for v in variants}
    runs = []
    for i, (p, v, line) in enumerate(plan, 1):
        stream, code, cost = run_once(p, line, args.max_turns, args.model)
        c = count_reads(stream, p["labels"])
        if args.streams:
            args.streams.mkdir(parents=True, exist_ok=True)
            (args.streams / f"{i:03d}-{v}.jsonl").write_text(stream)
        t = totals[v]
        for k in ("relevant", "noise", "other", "pulls"):
            t[k] += c[k]
        t["runs"] += 1
        t["cost_usd"] += cost or 0.0
        runs.append({"qid": p["qid"], "repo": p["repo"], "variant": v, "has_relevant": "relevant" in p["labels"].values(),
                     "shown": [r["page"] for r in rows.get(p["qid"], [])], "line": line, "exit": code, "cost_usd": cost, **c})
        print(f"{i}/{len(plan)} {p['qid']} {v}: relevant {c['relevant']}, noise {c['noise']}, other {c['other']}, exit {code}", file=sys.stderr)
    result = {"replay": str(args.replay), "sample": args.sample, "seed": args.seed, "max_turns": args.max_turns, "variants": totals, "runs": runs}
    text = json.dumps(result, indent=1)
    if args.out:
        args.out.write_text(text + "\n")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
