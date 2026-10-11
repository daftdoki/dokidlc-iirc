# /// script
# requires-python = ">=3.12"
# dependencies = ["numpy>=2", "pyyaml>=6"]
# ///
"""Regenerate bin/fingerprints.json: the probe sentence embedded as a document by each model's build on this machine.

Usage: fingerprints.py [--host URL]

Each ollama model comes from the host (default http://127.0.0.1:11434), through the
first of its ollama names that the host has, so qwen3 0.6B is its F16 build where the
host has it. A model the host lacks is left out, and `iirc doctor` skips its check
with a note. MiniLM runs through bin/iirc-cpu, its files fetched at the pinned commit
into a temporary directory. The script pulls no model, and it writes nothing but
bin/fingerprints.json: config, state, and data go to the temporary directory too.
"""
import argparse
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

PROBE = "A page records what a past session learned, such as the fix for a command that failed twice before it worked."


def entry_for(model, host: str):
    """(entry, build) for the model's build on this machine, or None when the host lacks every ollama name of it."""
    if "onnx" in model.names:
        iirc.fetch_minilm()
        ok, out = iirc.cpu_check()
        if not ok:
            sys.exit(f"bin/iirc-cpu could not run {model.id}: {out[-500:]}")
        name = model.names["onnx"][0]
        return iirc.Entry(model.id, iirc.CPU, "onnx", name), f"{name} through onnxruntime, fp32"
    tags = iirc.ollama_tags(host)
    name = iirc.first_build(model, tags) if tags is not None else None
    if name is None:
        return None
    build = iirc.ollama_build(host, name)
    return iirc.Entry(model.id, host, "ollama", name), f"{name} through ollama" + (f", {build}" if build else "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default=iirc.LOCAL_OLLAMA, help="the ollama host; default %(default)s")
    args = parser.parse_args()
    host = iirc.host_url(args.host)
    out = {"probe": PROBE, "models": {}}
    iirc.fingerprints = lambda: {"probe": PROBE, "models": {}}   # probe_vector reads the probe from here
    with tempfile.TemporaryDirectory(prefix="iirc-fingerprints-") as tmp:
        for var in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME"):
            os.environ[var] = str(Path(tmp) / var.lower())
        for model in iirc.iirc_embed.MODELS.values():
            found = entry_for(model, host)
            if found is None:
                print(f"{model.id}: {host} has none of {', '.join(model.names['ollama'])}; left out", file=sys.stderr)
                continue
            entry, build = found
            vec = iirc.probe_vector(entry)
            if vec is None or len(vec) != model.dims:
                sys.exit(f"{model.id}: {build} gave " + ("no vector" if vec is None else f"a {len(vec)}-wide vector, not {model.dims}"))
            out["models"][model.id] = {"build": build, "vector": [round(float(x), 5) for x in vec]}
            print(f"{model.id}: {build}", file=sys.stderr)
    # one line per vector, so a diff of the file shows which model changed
    lines = [f'  "probe": {json.dumps(out["probe"])},', '  "models": {']
    items = list(out["models"].items())
    for i, (mid, ref) in enumerate(items):
        lines.append(f'    {json.dumps(mid)}: {{"build": {json.dumps(ref["build"])}, "vector": {json.dumps(ref["vector"])}}}'
                     + ("," if i < len(items) - 1 else ""))
    (ROOT / "bin" / "fingerprints.json").write_text("{\n" + "\n".join(lines) + "\n  }\n}\n")


if __name__ == "__main__":
    main()
