"""Embedding and the vector store behind iirc's semantic search. bin/iirc imports it.

MODELS is the table of embedding models iirc knows: each one's backend, its
query and document prefixes, its dimensions, its recall knobs, and the page
text it embeds. For nomic the text is what memoryfield-tool embeds, so
distances match the tool's: `search_document: ` plus the raw page file cut at
8,192 bytes, and `search_query: ` plus the query.

Backends: ollama's /api/embed with truncate on; an OpenAI-compatible
/v1/embeddings; and onnx, which runs bin/iirc-cpu (its own uv script, with
onnxruntime and tokenizers) and returns one row per window of a page.

A store is one npz file per store field and model: `names`, `sha` (sha256 of
each page file), `vecs` (float32), and, when a page has more than one row,
`owner` (the page index of each row). A page's distance is its best row's.

numpy is imported inside the functions that need it, so a command that never
searches does not pay for the import.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple


class Model(NamedTuple):
    id: str                 # the name the backend knows it by
    backend: str            # "ollama", "openai" (an OpenAI-compatible URL), or "onnx" (bin/iirc-cpu on this CPU)
    query_prefix: str
    doc_prefix: str
    dims: int
    knobs: dict[str, tuple[float, float, float]]   # recall knob: (default, low, high) on this model's distance scale
    cut: float              # a page farther than this never reaches the gate
    text: str = "raw"       # "raw": the page file cut at DOC_BYTES; "plain": title, summary, topics, body before Sources


# The recall knobs differ per model because distances do: relevant pairs sit at a median 0.36 for
# nomic, 0.53 for qwen3, and 0.64 for embeddinggemma (evidence 6-models.md). MiniLM's defaults keep
# the share of relevant pairs nomic's keep (evidence 7-cpu-tier.md); the others take nomic's until a sweep.
# nomic keeps memoryfield-tool's 0.45 cut; the others cut at the top of their knob range.
_WIDE = {"semantic_only": (0.28, 0.10, 0.90), "both": (0.38, 0.10, 0.90)}
_QWEN3_QUERY = "Instruct: Given a request to a coding agent, retrieve the memory pages that help with it\nQuery: "
MODELS: dict[str, Model] = {m.id: m for m in (
    Model("nomic-embed-text", "ollama", "search_query: ", "search_document: ", 768,
          {"semantic_only": (0.28, 0.10, 0.60), "both": (0.38, 0.10, 0.60)}, 0.45),
    Model("qwen3-embedding:0.6b", "ollama", _QWEN3_QUERY, "", 1024, dict(_WIDE), 0.90),
    Model("embeddinggemma", "ollama", "task: search result | query: ", "title: none | text: ", 768, dict(_WIDE), 0.90),
    Model("qwen3-embedding", "openai", _QWEN3_QUERY, "", 1024, dict(_WIDE), 0.90),
    Model("all-minilm-l6-v2", "onnx", "", "", 384, {"semantic_only": (0.50, 0.10, 0.90), "both": (0.58, 0.10, 0.90)}, 0.90, "plain"),
)}
DEFAULT_MODEL = "nomic-embed-text"

# all-minilm-l6-v2's files, fetched by `iirc setup --cpu` at a pinned commit and checked against these sha256 values.
# The fp32 model, not the 23 MB int8 one: one file, so every machine computes the same vectors.
MINILM_REPO = "sentence-transformers/all-MiniLM-L6-v2"
MINILM_COMMIT = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
MINILM_FILES = {   # file name here: (path in the repository, sha256)
    "model.onnx": ("onnx/model.onnx", "6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452"),
    "tokenizer.json": ("tokenizer.json", "be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037"),
}

DOC_BYTES = 8192            # memoryfield-tool cuts the page file here before embedding
EMBED_TIMEOUT = 30.0        # per request; a cold model load measured 13.6 s, and the recall hook stops at 5 s anyway
CPU_TIMEOUT = 120.0         # bin/iirc-cpu per batch; its first run may still be installing onnxruntime
BATCH = 16                  # pages per request when indexing


class Backend(NamedTuple):
    model: Model
    url: str = ""                    # the ollama host, or the OpenAI-compatible base URL
    cpu: tuple[str, str] = ("", "")  # onnx: bin/iirc-cpu and the directory holding the model files


class Vectors(NamedTuple):
    names: list[str]
    sha: list[str]
    vecs: object            # numpy float32 array, one row per page, or per window when owner is set
    owner: object = None    # numpy int array: the index in names of each row; None when row i is page i


def table_name(model_id: str) -> str:
    """The model's [recall.NAME] table in .claude/iirc.toml, and its vector store's file name."""
    return model_id.replace(":", "-")


def plain_text(raw: bytes) -> str:
    """Title, summary, and topics from the frontmatter, then the body cut before `## Sources`; no YAML."""
    import yaml
    text = raw.decode("utf-8", errors="ignore")
    fm, body = {}, text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            try:
                fm = yaml.safe_load(text[4:end]) or {}
            except yaml.YAMLError:
                fm = {}
            body = text[end + 5:]
    fm = fm if isinstance(fm, dict) else {}
    topics = fm.get("topics") if isinstance(fm.get("topics"), list) else []
    body = re.split(r"(?m)^## Sources\s*$", body)[0].rstrip() + "\n"
    return f"{fm.get('title', '')}\n{fm.get('summary', '')}\nTopics: {', '.join(str(t) for t in topics)}\n\n{body}"


def doc_text(raw: bytes, model: Model = MODELS[DEFAULT_MODEL]) -> str:
    if model.text == "plain":
        return plain_text(raw)
    return model.doc_prefix + raw[:DOC_BYTES].decode("utf-8", errors="ignore")


def query_text(query: str, model: Model = MODELS[DEFAULT_MODEL]) -> str:
    return model.query_prefix + query


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def store_path(cache: Path, field: str, model: str = DEFAULT_MODEL) -> Path:
    return cache / "dokidlc-iirc" / "vectors" / field / f"{table_name(model)}.npz"


def _post(url: str, body: dict, timeout: float):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def run_cpu(backend: Backend, texts: list[str], kind: str):
    """(vecs, owner) from bin/iirc-cpu, or None when it fails."""
    import numpy as np
    script, model_dir = backend.cpu
    try:
        out = subprocess.run([script, "embed", kind, model_dir], input=json.dumps(texts).encode(), capture_output=True,
                             timeout=CPU_TIMEOUT, check=True).stdout
        with np.load(io.BytesIO(out), allow_pickle=False) as data:
            return data["vecs"], data["owner"]
    except (subprocess.SubprocessError, OSError, KeyError, ValueError):
        return None


def embed(backend: Backend, texts: list[str], kind: str = "doc", timeout: float = EMBED_TIMEOUT):
    """One float32 block per text (one row, or one per window), or None when the backend fails or answers with something else."""
    import numpy as np
    if not texts:
        return []
    try:
        if backend.model.backend == "onnx":
            got = run_cpu(backend, texts, kind)
            if got is None:
                return None
            vecs, owner = np.asarray(got[0], dtype=np.float32), np.asarray(got[1])
            if vecs.ndim != 2 or len(owner) != len(vecs):
                return None
            parts = [vecs[owner == i] for i in range(len(texts))]
            return parts if all(len(p) for p in parts) else None
        if backend.model.backend == "openai":
            data = _post(backend.url + "/v1/embeddings", {"model": backend.model.id, "input": texts}, timeout)["data"]
            rows = [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]
        else:
            rows = _post(backend.url + "/api/embed", {"model": backend.model.id, "input": texts, "truncate": True}, timeout).get("embeddings")
        vecs = np.asarray(rows, dtype=np.float32)
    except (urllib.error.URLError, OSError, ValueError, TypeError, AttributeError, KeyError):
        return None
    if vecs.ndim != 2 or len(vecs) != len(texts):
        return None
    return [vecs[i:i + 1] for i in range(len(texts))]


def embed_query(backend: Backend, query: str):
    """The query's vector, or None."""
    got = embed(backend, [query_text(query, backend.model)], "query")
    return got[0][0] if got else None


def load(path: Path) -> Vectors | None:
    """The store at path, or None when it is missing or not a store this module wrote."""
    import numpy as np
    try:
        with np.load(path, allow_pickle=False) as data:
            names, shas, vecs = [str(n) for n in data["names"]], [str(s) for s in data["sha"]], data["vecs"]
            owner = data["owner"] if "owner" in data.files else None
    except (OSError, KeyError, ValueError):
        return None
    if vecs.dtype != np.float32 or vecs.ndim != 2 or len(names) != len(shas):
        return None
    if owner is None and len(vecs) != len(names):
        return None
    if owner is not None and (len(owner) != len(vecs) or (len(owner) and not 0 <= owner.min() <= owner.max() < len(names))):
        return None
    return Vectors(names, shas, vecs, owner)


def save(path: Path, v: Vectors) -> None:
    """Write through a temporary file, so a search reading the store never sees half of one."""
    import numpy as np
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays = {"names": np.asarray(v.names, dtype=str), "sha": np.asarray(v.sha, dtype=str), "vecs": np.asarray(v.vecs, dtype=np.float32)}
    if v.owner is not None:
        arrays["owner"] = np.asarray(v.owner, dtype=np.int64)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".npz")
    try:
        with os.fdopen(fd, "wb") as f:
            np.savez(f, **arrays)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def page_blocks(v: Vectors) -> dict[str, tuple[str, object]]:
    """name: (sha, its rows) for each page in the store."""
    import numpy as np
    if v.owner is None:
        return {n: (s, v.vecs[i:i + 1]) for i, (n, s) in enumerate(zip(v.names, v.sha))}
    owner = np.asarray(v.owner)
    return {n: (s, v.vecs[owner == i]) for i, (n, s) in enumerate(zip(v.names, v.sha))}


def build(rows: list[tuple[str, str, object]], dims: int) -> Vectors:
    """A store from (name, sha, rows) in name order; owner only when some page has other than one row."""
    import numpy as np
    vecs = np.concatenate([b for _, _, b in rows]).astype(np.float32) if rows else np.zeros((0, dims), dtype=np.float32)
    owner = None
    if any(len(b) != 1 for _, _, b in rows):
        owner = np.concatenate([np.full(len(b), i, dtype=np.int64) for i, (_, _, b) in enumerate(rows)])
    return Vectors([n for n, _, _ in rows], [s for _, s, _ in rows], vecs, owner)


def refresh(path: Path, pages: dict[str, bytes], backend: Backend, limit: int | None = None, full: bool = False) -> Vectors:
    """The store for these pages: a page whose sha changed, or that is new, is embedded; a page gone is dropped.

    With `limit`, more changed pages than that are embedded not at all and left
    out of the result. With `full`, every page is embedded again, and a page the
    embed failed for keeps its old vector if its file has not changed. A failed
    embed leaves a changed page out.
    """
    old = load(path)
    have = page_blocks(old) if old else {}
    shas = {name: sha(raw) for name, raw in pages.items()}
    stale = sorted(n for n in pages if full or have.get(n, (None,))[0] != shas[n])
    fresh: dict[str, object] = {}
    if stale and (limit is None or len(stale) <= limit):
        for start in range(0, len(stale), BATCH):
            chunk = stale[start:start + BATCH]
            got = embed(backend, [doc_text(pages[n], backend.model) for n in chunk], "doc")
            if got is None:
                break
            fresh.update(zip(chunk, got))
    rows = []
    for name in sorted(pages):
        if name in fresh:
            rows.append((name, shas[name], fresh[name]))
        elif name in have and have[name][0] == shas[name]:
            rows.append((name, shas[name], have[name][1]))
    dims = rows[0][2].shape[1] if rows else (old.vecs.shape[1] if old else 0)
    current = build(rows, dims)
    # a changed page left unembedded is dropped: with no row it reads as new, which is the same thing
    if fresh or (old is not None and old.names != current.names):
        save(path, current)
    return current


def distances(v: Vectors, qvec, max_distance: float) -> list[tuple[float, str]]:
    """(cosine distance, page) for each page at or under max_distance, nearest first. A page's distance is its best row's."""
    import numpy as np
    if not v.names:
        return []
    q = np.asarray(qvec, dtype=np.float64)
    m = np.asarray(v.vecs, dtype=np.float64)
    norms = np.linalg.norm(m, axis=1) * np.linalg.norm(q)
    with np.errstate(divide="ignore", invalid="ignore"):
        d = 1.0 - (m @ q) / norms
    owner = np.arange(len(v.names)) if v.owner is None else np.asarray(v.owner)
    best = np.full(len(v.names), np.inf)
    ok = np.isfinite(d)
    np.minimum.at(best, owner[ok], d[ok])
    return sorted((float(x), n) for x, n in zip(best, v.names) if np.isfinite(x) and x <= max_distance)


def page_rows(v: Vectors) -> list[tuple[str, str, object]]:
    """(name, sha, one vector) per page, for page-to-page distances: a page with windows gets the mean of its unit rows."""
    import numpy as np
    out = []
    for name, (h, rows) in page_blocks(v).items():
        if len(rows) == 1:
            out.append((name, h, rows[0]))
        elif len(rows):
            out.append((name, h, (rows / np.maximum(np.linalg.norm(rows, axis=1, keepdims=True), 1e-12)).mean(axis=0)))
    return out
