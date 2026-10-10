"""Embedding and the vector store behind iirc's semantic search. bin/iirc imports it.

The text embedded is what memoryfield-tool embeds, so distances match the
tool's: `search_document: ` plus the raw page file cut at 8,192 bytes, and
`search_query: ` plus the query, through ollama's /api/embed with truncate on.
A store is one npz file per store field and model: `names`, `sha` (sha256 of
each page file), and `vecs` (float32, one row per page).

numpy is imported inside the functions that need it, so a command that never
searches does not pay for the import.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

MODEL = "nomic-embed-text"
QUERY_PREFIX = "search_query: "
DOC_PREFIX = "search_document: "
DOC_BYTES = 8192            # memoryfield-tool cuts the page file here before embedding
MAX_DISTANCE = 0.45         # memoryfield-tool's default: a page past it never reached the semantic half
EMBED_TIMEOUT = 30.0        # per request; a cold model load measured 13.6 s, and the recall hook stops at 5 s anyway
BATCH = 16                  # pages per request when indexing


class Vectors(NamedTuple):
    names: list[str]
    sha: list[str]
    vecs: object            # numpy float32 array, len(names) x dims


def doc_text(raw: bytes) -> str:
    return DOC_PREFIX + raw[:DOC_BYTES].decode("utf-8", errors="ignore")


def query_text(query: str) -> str:
    return QUERY_PREFIX + query


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def store_path(cache: Path, field: str, model: str = MODEL) -> Path:
    return cache / "dokidlc-iirc" / "vectors" / field / f"{model.replace(':', '-')}.npz"


def embed(base_url: str, texts: list[str], model: str = MODEL, timeout: float = EMBED_TIMEOUT):
    """One float32 row per text, or None when the host fails, times out, or answers with something else."""
    import numpy as np
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    req = urllib.request.Request(base_url + "/api/embed", data=json.dumps({"model": model, "input": texts, "truncate": True}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            rows = json.load(resp).get("embeddings")
        vecs = np.asarray(rows, dtype=np.float32)
    except (urllib.error.URLError, OSError, ValueError, TypeError, AttributeError):
        return None
    return vecs if vecs.ndim == 2 and len(vecs) == len(texts) else None


def load(path: Path) -> Vectors | None:
    """The store at path, or None when it is missing or not a store this module wrote."""
    import numpy as np
    try:
        with np.load(path, allow_pickle=False) as data:
            names, shas, vecs = [str(n) for n in data["names"]], [str(s) for s in data["sha"]], data["vecs"]
    except (OSError, KeyError, ValueError):
        return None
    if vecs.dtype != np.float32 or vecs.ndim != 2 or not len(names) == len(shas) == len(vecs):
        return None
    return Vectors(names, shas, vecs)


def save(path: Path, v: Vectors) -> None:
    """Write through a temporary file, so a search reading the store never sees half of one."""
    import numpy as np
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".npz")
    try:
        with os.fdopen(fd, "wb") as f:
            np.savez(f, names=np.asarray(v.names, dtype=str), sha=np.asarray(v.sha, dtype=str), vecs=np.asarray(v.vecs, dtype=np.float32))
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def refresh(path: Path, pages: dict[str, bytes], base_url: str, limit: int | None = None, full: bool = False,
            model: str = MODEL) -> Vectors:
    """The store for these pages: a page whose sha changed, or that is new, is embedded; a page gone is dropped.

    With `limit`, more changed pages than that are embedded not at all and left
    out of the result. With `full`, every page is embedded again, and a page the
    embed failed for keeps its old vector if its file has not changed. A failed
    embed leaves a changed page out.
    """
    import numpy as np
    old = load(path)
    have = {n: (s, i) for i, (n, s) in enumerate(zip(old.names, old.sha))} if old else {}
    shas = {name: sha(raw) for name, raw in pages.items()}
    stale = sorted(n for n in pages if full or have.get(n, (None,))[0] != shas[n])
    fresh: dict[str, object] = {}
    if stale and (limit is None or len(stale) <= limit):
        for start in range(0, len(stale), BATCH):
            chunk = stale[start:start + BATCH]
            vecs = embed(base_url, [doc_text(pages[n]) for n in chunk], model)
            if vecs is None:
                break
            fresh.update(zip(chunk, vecs))
    names, keep_sha, rows = [], [], []
    for name in sorted(pages):
        if name in fresh:
            names.append(name); keep_sha.append(shas[name]); rows.append(fresh[name])
        elif name in have and have[name][0] == shas[name]:
            names.append(name); keep_sha.append(shas[name]); rows.append(old.vecs[have[name][1]])
    dims = len(rows[0]) if rows else (old.vecs.shape[1] if old else 0)
    current = Vectors(names, keep_sha, np.asarray(rows, dtype=np.float32).reshape(len(rows), dims))
    # a changed page left unembedded is dropped: with no row it reads as new, which is the same thing
    if fresh or (old is not None and old.names != current.names):
        save(path, current)
    return current


def distances(v: Vectors, qvec, max_distance: float = MAX_DISTANCE) -> list[tuple[float, str]]:
    """(cosine distance, page) for each page at or under max_distance, nearest first. Distance is 1 - cosine similarity."""
    import numpy as np
    if not v.names:
        return []
    q = np.asarray(qvec, dtype=np.float64)
    m = np.asarray(v.vecs, dtype=np.float64)
    norms = np.linalg.norm(m, axis=1) * np.linalg.norm(q)
    with np.errstate(divide="ignore", invalid="ignore"):
        d = 1.0 - (m @ q) / norms
    return sorted((float(x), n) for x, n in zip(d, v.names) if np.isfinite(x) and x <= max_distance)
