#!/usr/bin/env python3
"""Grade one run directory: grade.py <run_dir> [...]. Writes grading.json beside transcript.jsonl.

Every assertion reads the transcript, the plugin's log, or the field after the run.
Nothing here is a judgement call, so the same run always grades the same way.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

FM_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)


def load(run: Path):
    events = [json.loads(l) for l in (run / "transcript.jsonl").read_text().splitlines() if l.strip()]
    calls = []   # (index, tool, input, result_text)
    results = {}
    for e in events:
        if e.get("type") == "user":
            for c in e["message"]["content"]:
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    cc = c.get("content")
                    results[c["tool_use_id"]] = cc if isinstance(cc, str) else " ".join(x.get("text", "") for x in cc if isinstance(x, dict))
    for e in events:
        if e.get("type") == "assistant":
            for c in e["message"]["content"]:
                if c["type"] == "tool_use":
                    calls.append({"tool": c["name"], "input": c["input"], "id": c["id"]})
    for c in calls:
        c["result"] = results.get(c["id"], "")
    # a call the guard denied never ran; the refusal is the mechanism working, so it grades as if never attempted
    calls = [c for c in calls if not str(c["result"]).startswith("PreToolUse:Bash hook error")]
    texts = [c["text"] for e in events if e.get("type") == "assistant" for c in e["message"]["content"] if c["type"] == "text" and c["text"].strip()]
    answer = "\n\n".join(texts)
    (run / "outputs" / "answer.md").write_text(answer + "\n")
    log = [json.loads(l) for l in (run / "outputs" / "iirc-log.jsonl").read_text().splitlines() if l.strip()]
    field = {}
    for p in sorted((run / "outputs" / "iirc-after").glob("*.md")):
        if p.name == "index.md":
            continue
        m = FM_RE.match(p.read_text())
        fm = {}
        body = p.read_text()
        if m:
            body = m.group(2)
            for line in m.group(1).splitlines():
                if ":" in line and not line.startswith(" ") and not line.startswith("-"):
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip("'\"")
        field[p.name] = {"fm": fm, "body": body, "text": p.read_text(), "bytes": p.stat().st_size}
    return calls, answer, log, field


def bash(calls):
    return [(i, c["input"].get("command", "")) for i, c in enumerate(calls) if c["tool"] == "Bash"]


def first_index(calls, pattern):
    """Step of the first Bash call matching pattern, as step + offset/1000 so order inside one call counts."""
    for i, cmd in bash(calls):
        m = re.search(pattern, cmd)
        if m:
            return i + min(m.start(), 999) / 1000
    return None


def any_index(calls, pattern):
    out = []
    for i, cmd in bash(calls):
        m = re.search(pattern, cmd)
        if m:
            out.append(i + min(m.start(), 999) / 1000)
    return out


def wrote_page_directly(calls):
    """Steps that touch a page file without going through `iirc write`: the Write/Edit tools, or a shell redirect into .iirc/."""
    out = [i for i, c in enumerate(calls) if c["tool"] in ("Write", "Edit", "MultiEdit") and "/.iirc/" in str(c["input"].get("file_path", ""))]
    out += [i for i, cmd in bash(calls) if re.search(r"(>>?|tee(?: -a)?)\s*\.?\S*\.iirc/\S+\.md", cmd)]
    return sorted(out)


def sources_dated(page):
    body = page["body"]
    return "## Sources" in body and re.search(r"2026-\d\d-\d\d", body.split("## Sources", 1)[1]) is not None


def one_sentence(s):
    return len(re.findall(r"[.!?](\s|$)", s.strip())) <= 1


def grade(run: Path, eval_name: str):
    calls, answer, log, field = load(run)
    ex = []

    def add(text, passed, evidence):
        ex.append({"text": text, "passed": bool(passed), "evidence": str(evidence)[:400]})

    fixture_pages = {"ledger": 4, "syncproj": 2, "devserver": 3}
    reads = any_index(calls, r"iirc (read|pull)\b")
    searches = any_index(calls, r"iirc (search|pull)\b")

    if eval_name in ("search-before-debug", "search-when-hook-is-silent"):
        first_fix = first_index(calls, r"make db|build_db\.py")
        first_mem = min(searches + reads, default=None)
        add("IIRC is consulted (search, read, or pull) before the fix is applied",
            first_mem is not None and (first_fix is None or first_mem < first_fix),
            f"first iirc call at step {first_mem}, make db at step {first_fix}")
        cats = any_index(calls, r"(cat|head|sed|tail|less|more)\s+[^;|&>]*\.iirc/[a-z0-9-]+\.md")
        add("Pages are read with iirc read or pull, not cat", not cats, f"cat of a page at steps {cats}")
        read_page = any_index(calls, r"iirc (read|pull).*ledger-tests-need-make-db")
        make_db = first_index(calls, r"make db|build_db\.py")
        add("The agent reads ledger-tests-need-make-db.md before running make db",
            read_page and (make_db is None or min(read_page) < make_db),
            f"page read at steps {read_page}, make db at step {make_db}")
        test_runs = [(i, c["result"]) for i, c in enumerate(calls) if c["tool"] == "Bash" and re.search(r"make test|unittest", c["input"].get("command", ""))]
        last_ok = bool(test_runs) and ("OK" in test_runs[-1][1] and "FAILED" not in test_runs[-1][1])
        add("The tests pass at the end of the run", last_ok, f"last test run at step {test_runs[-1][0] if test_runs else None}: {test_runs[-1][1][-120:] if test_runs else 'no test run'}")
        add("No new page: the field still holds 4 pages", len(field) == 4, f"{len(field)} pages: {sorted(field)}")
        pg = field.get("ledger-tests-need-make-db.md", {})
        add("ledger-tests-need-make-db.md carries a verified stamp after the run", "verified" in pg.get("fm", {}), f"frontmatter keys: {sorted(pg.get('fm', {}))}")
        add("The reply names make db and the missing database as the cause", re.search(r"make db", answer) and re.search(r"sample\.db|database|gitignore", answer), answer[:200])
        add("No page file is written except through iirc write", not wrote_page_directly(calls), f"direct writes at steps {wrote_page_directly(calls)}")

    elif eval_name == "write-after-learning":
        synced = [i for i, c in enumerate(calls) if "12 records synced" in c["result"]]
        add("sync.py completes and prints the synced count", bool(synced), f"synced at steps {synced}")
        new = {n: p for n, p in field.items() if n not in ("syncproj-state-json-is-read-by-the-report-tool.md", "syncproj-store-port-7433.md")}
        add("One or two new pages are written, one per finding (the lock, the route)", 1 <= len(new) <= 2, f"new pages: {sorted(new)}")
        ps = list(new.values())
        alltext = "\n".join(p["text"] for p in ps)
        add("Every new page's kind is procedure, environment, or finding, not decision", ps and all(p["fm"].get("kind") in ("procedure", "environment", "finding") for p in ps), [p["fm"].get("kind") for p in ps])
        add("Every new page has a Sources section with a date", ps and all(sources_dated(p) for p in ps), [("Sources" in p["body"], bool(re.search(r"2026-\d\d-\d\d", p["body"]))) for p in ps])
        add("A new page names the command that worked, with SYNC_PROFILE=local", "SYNC_PROFILE=local" in alltext, alltext[:200])
        add("The new pages say what they work around: the stale lock and the vpn route", re.search(r"lock", alltext, re.I) and re.search(r"vpn|route|E_NOROUTE", alltext, re.I), "")
        add("Every new page's summary is one sentence", ps and all(one_sentence(p["fm"].get("summary", "")) for p in ps), [p["fm"].get("summary") for p in ps])
        add("Every new page is under 8KB and is more than a command and a path", ps and all(p["bytes"] < 8192 and len(p["body"].strip()) > 120 for p in ps), [p["bytes"] for p in ps])
        add("No page file is written except through iirc write", not wrote_page_directly(calls), f"direct writes at steps {wrote_page_directly(calls)}")
        add("An iirc search runs before the first sync attempt", (min(searches + reads, default=10**6) < (first_index(calls, r"sync\.py") or 10**6)), f"iirc at {min(searches + reads, default=None)}, sync at {first_index(calls, r'sync\.py')}")

    elif eval_name == "suspect-page-same-turn":
        read_page = any_index(calls, r"iirc (read|pull).*dev-server-port|iirc pull")
        add("The agent reads dev-server-port.md", bool(read_page), f"steps {read_page}")
        script_write = next((i for i, c in enumerate(calls) if c["tool"] in ("Write", "Edit") and "healthcheck" in str(c["input"].get("file_path", ""))), None)
        if script_write is None:
            script_write = first_index(calls, r"healthcheck\.sh")
        looked = [i for i, c in enumerate(calls) if (c["tool"] == "Bash" and re.search(r"git (diff|log|show).*config\.md|cat .*config\.md|settings\.py", c["input"].get("command", ""))) or (c["tool"] == "Read" and re.search(r"config\.md|settings\.py", str(c["input"].get("file_path", ""))))]
        add("The agent inspects docs/config.md or server/settings.py before writing the script", looked and (script_write is None or min(looked) < script_write), f"looked at steps {looked}, script written at {script_write}")
        hc = run / "repo" / "scripts" / "healthcheck.sh"
        text = hc.read_text() if hc.is_file() else ""
        add("scripts/healthcheck.sh exists, uses port 9090, and does not mention 8080", hc.is_file() and "9090" in text and "8080" not in text, text[:200] or "missing")
        if hc.is_file():
            r = subprocess.run(["sh", str(hc)], capture_output=True, text=True, timeout=30)
            add("healthcheck.sh exits non-zero when nothing listens", r.returncode != 0, f"exit {r.returncode}: {(r.stdout + r.stderr)[:120]}")
        else:
            add("healthcheck.sh exits non-zero when nothing listens", False, "missing")
        pg = field.get("dev-server-port.md")
        fixed = pg is None or ("9090" in pg["fm"].get("title", "") + pg["fm"].get("summary", "") and "9090" in pg["body"])
        add("dev-server-port.md is rewritten to say 9090 or deleted", fixed, "deleted" if pg is None else pg["fm"].get("summary", ""))
        verify_steps = [i for i, cmd in bash(calls) if re.search(r"iirc verify.*dev-server-port", cmd)]
        write_steps = [i for i, cmd in bash(calls) if re.search(r"iirc (write|delete).*dev-server-port", cmd)]
        add("The stale page is not verified before it is rewritten", not verify_steps or (write_steps and min(write_steps) < min(verify_steps)), f"verify at {verify_steps}, write/delete at {write_steps}")
        add("No page file is written except through iirc write", not wrote_page_directly(calls), f"direct writes at steps {wrote_page_directly(calls)}")
        if pg is not None:
            add("The rewritten page keeps a Sources section with a date", sources_dated(pg), "")

    elif eval_name == "remember-a-fact-a-file-holds":
        first_write = first_index(calls, r"iirc write")
        consulted = searches + reads
        add("IIRC is consulted (search, read, or pull) before any write", consulted and (first_write is None or min(consulted) < first_write), f"consulted at {consulted}, write at {first_write}")
        add("No new page: the field still holds 4 pages", len(field) == 4, f"{len(field)} pages: {sorted(field)}")
        add("The reply names ledger-tests-need-make-db.md as already holding the fact", "ledger-tests-need-make-db" in answer, answer[:200])
        pg = field.get("ledger-tests-need-make-db.md", {})
        add("ledger-tests-need-make-db.md still has a Sources section with a date", pg and sources_dated(pg), "")
        thin = [n for n, p in field.items() if len(p["body"].strip()) < 120]
        add("No page's body is only a command and a path", not thin, f"thin pages: {thin}")
        add("No page file is written except through iirc write", not wrote_page_directly(calls), f"direct writes at steps {wrote_page_directly(calls)}")

    tools = {}
    for c in calls:
        tools[c["tool"]] = tools.get(c["tool"], 0) + 1
    passed = sum(1 for e in ex if e["passed"])
    out = {
        "expectations": ex,
        "summary": {"passed": passed, "failed": len(ex) - passed, "total": len(ex), "pass_rate": round(passed / len(ex), 2) if ex else 0},
        "execution_metrics": {"tool_calls": tools},
    }
    (run / "grading.json").write_text(json.dumps(out, indent=1) + "\n")
    print(f"{run.relative_to(run.parents[3])}: {passed}/{len(ex)}")


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        run = Path(arg).resolve()
        eval_name = run.parents[1].name.split("-", 2)[2]
        grade(run, eval_name)
