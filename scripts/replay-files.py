# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6"]
# ///
"""Build the replay files that `iirc tune sweep --replay` reads, from a quest's judged labels.

Usage: replay-files.py DATA_DIR

DATA_DIR holds agent-builder-labels-strict.jsonl, neckbeard-labels-strict.jsonl, and
neckbeard-prompts.jsonl; the script writes replay-agent-builder.jsonl and
replay-neckbeard.jsonl beside them. An agent-builder label names a session and a recall
key; its prompt comes from the tune evidence and, for the full text, the session's
transcript. A neckbeard label's qid is its prompt's session[:8]/uuid[:8]. It reads this
machine's iirc state and transcripts and writes nothing there.
"""
import importlib.util
import json
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_loader = SourceFileLoader("iirc", str(ROOT / "bin" / "iirc"))
_spec = importlib.util.spec_from_loader("iirc", _loader)
iirc = importlib.util.module_from_spec(_spec)
_loader.exec_module(iirc)

PROMPT_MAX = 8000
AGENT_BUILDER = Path.home() / "Code" / "agents" / "agent-builder"
NECKBEARD = [Path.home() / "Code" / "agents" / "agent-neckbeard", Path.home() / "Code" / "agents" / "neckbeard"]


def redact(text: str) -> str:
    """Secrets out first, then the cap, so the cap never leaves half a token behind."""
    for pattern in iirc.SECRET_PATTERNS.values():
        text = pattern.sub("[REDACTED]", text)
    return text[:PROMPT_MAX]


def join(labels: list[dict], prompts: dict[str, dict], repo: str) -> tuple[list[dict], list[str]]:
    """One replay row per label whose qid has a prompt, and the qids that have none."""
    rows, missing = [], []
    for lab in labels:
        p = prompts.get(lab["qid"])
        if p is None:
            if lab["qid"] not in missing:
                missing.append(lab["qid"])
            continue
        row = {"repo": repo, "qid": lab["qid"], "prompt": redact(p["prompt"]), "via": p["via"], "page": lab["page"], "label": lab["label"]}
        if p.get("excerpt"):
            row["excerpt"] = True
        rows.append(row)
    return rows, missing


def neckbeard_prompts(rows: list[dict]) -> dict[str, dict]:
    return {f"{r['session'][:8]}/{r['uuid'][:8]}": {"prompt": r["text"], "via": "prompt"} for r in rows if r.get("text")}


def recall_prompt(recall: dict, prompt_hash: str | None, tx: list[dict] | None) -> dict | None:
    """A recall's full prompt: the transcript's prompt by hash, else the one whose excerpt the evidence kept,
    else that excerpt, flagged. A failure recall's prompt is the command and its error as the evidence holds them."""
    if recall.get("via") == "failure":
        failed = recall.get("failed") or {}
        if not failed.get("command"):
            return None
        return {"prompt": "\n".join(x for x in (failed["command"], failed.get("error")) if x), "via": "failure"}
    excerpt = (recall.get("prompt") or {}).get("text")
    ts = iirc.parse_ts(recall.get("ts"))
    # a prompt typed twice joins to its last occurrence before the recall, as tune gather joins it
    before = [p for p in tx or [] if ts is None or p["ts"] < ts + 1]
    hit = next((p for p in reversed(before) if prompt_hash and p["hash"] == prompt_hash), None) \
        or next((p for p in reversed(before) if excerpt and iirc.clean(p["text"], 300) == excerpt), None)
    if hit:
        return {"prompt": hit["text"], "via": "prompt"}
    if excerpt:
        return {"prompt": excerpt, "via": "prompt", "excerpt": True}
    return None


def recall_hashes() -> dict[tuple[str, str], str]:
    """(session, recall key) to prompt hash, from the log and the prompts files."""
    out = {}
    for r in iirc.read_log():
        if r.get("cmd") == "recall" and r.get("prompt_hash"):
            out[(r.get("session"), r.get("recall_id") or r.get("ts"))] = r["prompt_hash"]
    for path in sorted((iirc.state_dir() / "prompts").glob("*.jsonl")):
        for r in iirc.read_prompts_file(path.stem):
            if r.get("recall_id") and r.get("prompt_hash"):
                out.setdefault((path.stem, r["recall_id"]), r["prompt_hash"])
    return out


def agent_builder_prompts(labels: list[dict]) -> dict[str, dict]:
    hashes = recall_hashes()
    claude = Path.home() / ".claude" / "projects" / "-Users-aaron-Code-agents-agent-builder"
    out = {}
    for session in sorted({lab["session"] for lab in labels}):
        evidence = json.loads((iirc.state_dir() / "tune" / f"{session}.json").read_text())
        path = Path(evidence.get("transcript") or claude / f"{session}.jsonl")
        tx = iirc.read_transcript(path)["prompts"] if path.is_file() else None
        for recall in evidence["recalls"]:
            p = recall_prompt(recall, hashes.get((session, recall["key"])), tx)
            if p:
                out[f"{session[:8]}/{recall['key']}"] = p
    return out


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write(path: Path, rows: list[dict], missing: list[str]) -> None:
    rows.sort(key=lambda r: (r["qid"], r["page"]))
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"{path.name}: {len(rows)} rows, {len({r['qid'] for r in rows})} prompts, {len(missing)} missing prompts, "
          f"{len({r['qid'] for r in rows if r.get('excerpt')})} excerpts")


def main(data: Path) -> None:
    labels = read_jsonl(data / "agent-builder-labels-strict.jsonl")
    for lab in labels:
        lab["qid"] = f"{lab['session'][:8]}/{lab['recall']}"
    write(data / "replay-agent-builder.jsonl", *join(labels, agent_builder_prompts(labels), str(AGENT_BUILDER)))
    repo = next((p for p in NECKBEARD if p.is_dir()), None)
    if repo is None:
        sys.exit("no neckbeard checkout at " + " or ".join(map(str, NECKBEARD)))
    prompts = neckbeard_prompts(read_jsonl(data / "neckbeard-prompts.jsonl"))
    write(data / "replay-neckbeard.jsonl", *join(read_jsonl(data / "neckbeard-labels-strict.jsonl"), prompts, str(repo)))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(Path(sys.argv[1]))
