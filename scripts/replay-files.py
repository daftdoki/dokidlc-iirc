# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6", "numpy>=2"]
# ///
"""Build the replay files that `iirc tune-suggestions evaluate-suggestion-thresholds --replay-prompts` reads, from a quest's judged labels.

Usage: replay-files.py DATA_DIR
       replay-files.py --pool MODEL... --replay SET=FILE...
       replay-files.py --merge DATA_DIR

DATA_DIR holds agent-builder-labels-strict.jsonl, neckbeard-labels-strict.jsonl, and
neckbeard-prompts.jsonl; the script writes replay-agent-builder.jsonl and
replay-neckbeard.jsonl beside them. An agent-builder label names a session and a recall
key; its prompt comes from the tune evidence and, for the full text, the session's
transcript. A neckbeard label's qid is its prompt's session[:8]/uuid[:8]. It reads this
machine's iirc state and transcripts and writes nothing there.

--pool prints, as JSON lines, the pages in each model's top POOL_DEPTH for a replay prompt
that the replay file has no label for, so they can be judged. A model searches through a
machine config of its own, with config, state, and cache in a temporary directory; the
repository's pages are read, never written. --merge adds the labels of each
pool-round-*.jsonl in DATA_DIR to replay-SET.jsonl, taking repo, prompt, and via from the
replay rows of the same qid.
"""
import argparse
import contextlib
import importlib.util
import json
import os
import sys
import tempfile
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
    return iirc.redact(text)[:PROMPT_MAX]


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
        or next((p for p in reversed(before) if excerpt and iirc.clean(iirc.redact(p["text"]), 300) == excerpt), None)
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


POOL_DEPTH = 3
POOL_ENV = ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "IIRC_CACHE_DIR")


def pool_rows(set_name: str, replay: list[dict], ranked: dict[str, dict[str, list[str]]]) -> list[dict]:
    """One row per (qid, page) in some model's top POOL_DEPTH with no label in the replay, naming the models that ranked it there."""
    labelled = {(r["qid"], iirc.base(r["page"])) for r in replay}
    found: dict[tuple[str, str], list[str]] = {}
    for model, per_qid in ranked.items():
        for qid, pages in per_qid.items():
            for page in pages[:POOL_DEPTH]:
                if (qid, page) not in labelled:
                    found.setdefault((qid, page), []).append(model)
    return [{"set": set_name, "qid": q, "page": p, "models": m} for (q, p), m in sorted(found.items())]


@contextlib.contextmanager
def model_machine(model_id: str, tmp: Path):
    """A machine whose config names this model, with its config, state, and cache under tmp; the environment comes back after."""
    model = iirc.iirc_embed.MODELS[model_id]
    if model.backend == "openai":
        sys.exit(f"{model_id} needs a URL; --pool takes the ollama and onnx models")
    old = {k: os.environ.get(k) for k in POOL_ENV}
    base = tmp / iirc.iirc_embed.table_name(model_id)
    for k in POOL_ENV:
        os.environ[k] = str(base / k.lower())
    real_background = iirc.index_in_background
    # a search that finds pages missing starts `iirc rebuild-search-index`, which stamps and commits the repository's index
    iirc.index_in_background = lambda store: None
    try:
        iirc.write_config_file({"semantic": True, "embedding": {"backend": model.backend, "model": model_id}})
        iirc._RESOLVED = None
        yield
    finally:
        iirc.index_in_background = real_background
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        iirc._CONFIG = iirc._RESOLVED = None


def ranked_pages(model_id: str, repo: Path, prompts: dict[str, tuple[str, str]], tmp: Path) -> dict[str, list[str]]:
    """Each prompt's pages in the order hybrid_search ranks them under this model, the order the gate sees, after a full index."""
    with model_machine(model_id, tmp):
        iirc.set_root(repo)
        iirc.reindex()
        for store in iirc.live_stores():
            have = iirc.iirc_embed.load(iirc.vector_path(store))
            if have is None or len(have.names) < len(iirc.list_pages(store.dir)):
                sys.exit(f"{model_id} embedded {len(have.names) if have else 0} of {len(iirc.list_pages(store.dir))} pages in {store.dir}; "
                         "is its backend running?")
        # the hook searches the person's words of a prompt, and a failure's query as it stands
        return {qid: [iirc.base(r["filename"]) for r in iirc.hybrid_search(iirc.person_text(p) if via == "prompt" else p)]
                for qid, (p, via) in prompts.items()}


def pool(models: list[str], replays: list[str]) -> None:
    for spec in replays:
        set_name, _, path = spec.partition("=")
        rows = read_jsonl(Path(path))
        repo = Path(rows[0]["repo"])
        prompts = {r["qid"]: (r["prompt"], r["via"]) for r in rows}
        with tempfile.TemporaryDirectory(prefix="iirc-pool-") as tmp:
            ranked = {m: ranked_pages(m, repo, prompts, Path(tmp)) for m in models}
        out = pool_rows(set_name, rows, ranked)
        for r in out:
            print(json.dumps(r, ensure_ascii=False))
        per_model = ", ".join(f"{m} {sum(m in r['models'] for r in out)}" for m in models)
        print(f"{set_name}: {len(prompts)} prompts, {len(out)} unlabelled pairs in the top {POOL_DEPTH}; per model: {per_model}", file=sys.stderr)


def merge_pool(replay: list[dict], labels: list[dict]) -> tuple[list[dict], int, int]:
    """The replay rows plus a row per label whose (qid, page) has none yet: (rows, added, skipped). A label whose qid the replay lacks is skipped."""
    prompts = {r["qid"]: r for r in replay}
    have = {(r["qid"], iirc.base(r["page"])) for r in replay}
    rows, added, skipped = list(replay), 0, 0
    for lab in labels:
        p = prompts.get(lab["qid"])
        if p is None or (lab["qid"], iirc.base(lab["page"])) in have:
            skipped += 1
            continue
        row = {"repo": p["repo"], "qid": lab["qid"], "prompt": p["prompt"], "via": p["via"], "page": lab["page"], "label": lab["label"]}
        if p.get("excerpt"):
            row["excerpt"] = True
        rows.append(row)
        have.add((lab["qid"], iirc.base(lab["page"])))
        added += 1
    return rows, added, skipped


def merge(data: Path) -> None:
    labels = [lab for path in sorted(data.glob("pool-round-*.jsonl")) for lab in read_jsonl(path)]
    for set_name in sorted({lab["set"] for lab in labels}):
        path = data / f"replay-{set_name}.jsonl"
        rows, added, skipped = merge_pool(read_jsonl(path), [lab for lab in labels if lab["set"] == set_name])
        print(f"{path.name}: {added} pool labels added, {skipped} skipped")
        write(path, rows, [])


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
    merge(data)   # a rebuild keeps the pool rounds' labels


if __name__ == "__main__":
    ap = argparse.ArgumentParser(usage=__doc__)
    ap.add_argument("data", nargs="?", type=Path)
    ap.add_argument("--pool", nargs="+", metavar="MODEL")
    ap.add_argument("--replay", nargs="+", metavar="SET=FILE")
    ap.add_argument("--merge", type=Path, metavar="DATA_DIR")
    a = ap.parse_args()
    if a.pool and a.replay:
        pool(a.pool, a.replay)
    elif a.merge:
        merge(a.merge)
    elif a.data:
        main(a.data)
    else:
        sys.exit(__doc__)
