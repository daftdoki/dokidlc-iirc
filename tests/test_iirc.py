"""Tests for scripts/iirc that need neither the tool nor ollama."""

import contextlib
import json
import os
import time
import re
import socket
import threading
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_loader = SourceFileLoader("iirc", str(ROOT / "bin" / "iirc"))
_spec = importlib.util.spec_from_loader("iirc", _loader)
iirc = importlib.util.module_from_spec(_spec)
_loader.exec_module(iirc)


@pytest.fixture(scope="session", autouse=True)
def _real_cache(tmp_path_factory):
    """One temp cache for the whole run; yields the real memoryfield-tool cache and its test-* entries before the run."""
    real = iirc.cache_dir() / "memoryfield-tool"
    before = {p.name for p in real.glob("test-*")}
    base = tmp_path_factory.mktemp("cache")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("IIRC_CACHE_DIR", str(base))
        mp.setenv("XDG_CACHE_HOME", str(base))
        yield real, before


@pytest.fixture(autouse=True)
def _machine_dirs(tmp_path_factory, monkeypatch):
    """Every test sees temp machine directories, never this machine's real config, data, or state."""
    base = tmp_path_factory.mktemp("xdg")
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(var, str(base / var.lower()))


def test_field_name_is_stable_and_distinct(tmp_path):
    a = tmp_path / "Agent_One"
    b = tmp_path / "agent-one"
    a.mkdir(); b.mkdir()
    assert iirc.field_name(a) == iirc.field_name(a)
    assert iirc.field_name(a) != iirc.field_name(b)
    assert iirc.NAME_RE.match(iirc.field_name(a))
    assert iirc.field_name(a).startswith("agent-one-")
    assert iirc.config_path(a) != iirc.config_path(b)   # two clones, two configs


def test_config_text_points_at_dot_iirc(tmp_path):
    text = iirc.config_text(tmp_path)
    assert f'location = "{(tmp_path / ".iirc").resolve()}"' in text
    assert 'index_location = "cache"' in text
    assert f"[memoryfields.{iirc.field_name(tmp_path)}]" in text


def test_normalize_host():
    assert iirc.normalize_host(None) == "http://127.0.0.1:11434"
    assert iirc.normalize_host("localhost:11434") == "http://localhost:11434"
    assert iirc.normalize_host("http://x:1/") == "http://x:1"
    assert iirc.normalize_host("https://x:1") == "https://x:1"


def test_host_guard_closed_port_returns_fast():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    assert iirc.host_answers(f"http://127.0.0.1:{port}", timeout=1.0) is False


def test_host_guard_silent_host_returns_within_timeout():
    """A host that accepts and never replies must not hang. This is the 75s case."""
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    stop = threading.Event()

    def hold():
        conns = []
        srv.settimeout(0.2)
        while not stop.is_set():
            try:
                conns.append(srv.accept()[0])
            except socket.timeout:
                pass
        for c in conns:
            c.close()

    t = threading.Thread(target=hold, daemon=True); t.start()
    import time
    start = time.monotonic()
    assert iirc.host_answers(f"http://127.0.0.1:{port}", timeout=1.0) is False
    assert time.monotonic() - start < 3.0
    stop.set(); t.join(); srv.close()


def test_read_pin(tmp_path):
    p = tmp_path / "pin"
    p.write_text("# comment\ntool_rev=abc123\nmodel = nomic-embed-text\n\n")
    assert iirc.read_pin(p) == {"tool_rev": "abc123", "model": "nomic-embed-text"}


def test_pin_matches_prefix_either_way():
    pin = {"tool_rev": "3e447e1d5c4840028cce3c05e70e7349923fc634"}
    assert iirc.pin_matches(pin, "3e447e1d5c4840028cce3c05e70e7349923fc634")
    assert iirc.pin_matches(pin, "3e447e1")
    assert not iirc.pin_matches(pin, "deadbeef")
    assert not iirc.pin_matches(pin, None)


def test_tokens_estimate():
    assert iirc.tokens(0) == 0
    assert iirc.tokens(4) == 1
    assert iirc.tokens(5) == 2


def test_strip_ansi():
    assert iirc.strip_ansi("\x1b[36m/a/b\x1b[39m\n") == "/a/b\n"


def test_parse_and_render_round_trip():
    text = "---\ntitle: T\nsummary: S\ntopics:\n- a\nkind: finding\ncreated: '2026-09-01T00:00:00Z'\n---\nbody\n\n## Sources\n\n- x\n"
    fm, body = iirc.parse_page(text)
    assert fm["topics"] == ["a"] and fm["created"] == "2026-09-01T00:00:00Z"
    out = iirc.render_page(fm, body)
    assert "created: '2026-09-01T00:00:00Z'" in out
    assert out.endswith("- x\n")
    assert iirc.parse_page(out) == (fm, body)


def test_parse_page_without_frontmatter():
    assert iirc.parse_page("just text\n") == ({}, "just text\n")


def test_validate_page_rules():
    good = {"title": "T", "summary": "S", "topics": ["a"], "kind": "finding"}
    assert iirc.validate_page("ok-page.md", good, "b\n\n## Sources\n\n- x\n") == []
    errs = iirc.validate_page("Bad_Name.md", {"title": "T"}, "no sources")
    assert any("page name" in e for e in errs)
    assert any("summary" in e for e in errs)
    assert any("topics" in e for e in errs)
    assert any("kind" in e for e in errs)
    assert any("Sources" in e and not e.startswith("warning:") for e in errs)   # an error, not a warning
    assert iirc.validate_page("ok-page.md", good, "b\n\n## sources\n\n- x\n") == []
    assert any("index.md" in e for e in iirc.validate_page("index.md", good, "## Sources\n"))


def test_fill_ref_from_git(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "a.md").write_text("one\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "one"], check=True)
    sha = subprocess.run(["git", "-C", str(tmp_path), "log", "-1", "--format=%h"], capture_output=True, text=True).stdout.strip()
    assert iirc.fill_ref("docs/a.md", tmp_path) == f"docs/a.md@{sha}"
    assert iirc.fill_ref("docs/a.md@abc1234", tmp_path) == "docs/a.md@abc1234"
    with pytest.raises(SystemExit):
        iirc.fill_ref("docs/missing.md", tmp_path)
    with pytest.raises(SystemExit):
        iirc.fill_ref("docs/a.md@nothex", tmp_path)


def test_doctor_ends_with_the_fix_hint_when_a_check_fails(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    (tmp_path / "CLAUDE.md").write_text("no paragraph here\n")
    with pytest.raises(SystemExit):
        iirc.main(["doctor"])
    out = capsys.readouterr().out
    assert "FAIL" in out and out.rstrip().endswith(iirc.FIX_HINT)


def test_stamp_index_keeps_the_head_and_drops_the_old_list(tmp_path):
    field = tmp_path / ".iirc"; field.mkdir()
    old = "---\ntitle: IIRC\n---\n\nHand-written intro.\n\n<!-- generated below -->\n<!-- iirc format 1, written by iirc abc1234 on 2026-10-01 -->\n\nTopics across 2 pages:\n\n- install (2)\n"
    (field / "index.md").write_text(old)
    iirc.stamp_index(field)
    assert (field / "index.md").read_text() == "---\ntitle: IIRC\n---\n\nHand-written intro.\n\n<!-- iirc format 1 -->\n"


def test_stamp_index_leaves_a_stamped_file_untouched(tmp_path):
    field = tmp_path / ".iirc"; field.mkdir()
    (field / "index.md").write_text("intro only\n")
    iirc.stamp_index(field)
    assert (field / "index.md").read_text() == "intro only\n\n<!-- iirc format 1 -->\n"
    before = (field / "index.md").stat().st_mtime_ns
    (field / "a.md").write_text("---\ntopics:\n- install\n---\nx\n")
    iirc.stamp_index(field)
    assert (field / "index.md").stat().st_mtime_ns == before   # a new page no longer rewrites it


def test_topics_counts_every_topic(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    (tmp_path / ".iirc" / "a.md").write_text("---\ntopics:\n- install\n- ollama\n---\nx\n")
    (tmp_path / ".iirc" / "b.md").write_text("---\ntopics:\n- install\n---\ny\n")
    iirc.main(["topics"])
    assert capsys.readouterr().out.splitlines() == ["install (2)", "ollama (1)"]


def _repo(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "a.md").write_text("one\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "one"], check=True)
    return subprocess.run(["git", "-C", str(tmp_path), "log", "-1", "--format=%h"], capture_output=True, text=True).stdout.strip()


def test_ref_changed_after_commit(tmp_path):
    import subprocess
    sha = _repo(tmp_path)
    assert iirc.ref_changed(f"docs/a.md@{sha}", tmp_path) is None
    (tmp_path / "docs" / "a.md").write_text("two\n")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qam", "two"], check=True)
    reason = iirc.ref_changed(f"docs/a.md@{sha}", tmp_path)
    assert reason and "changed since cited (1 commit)" in reason
    assert "not found" in iirc.ref_changed("docs/a.md@deadbeef", tmp_path)
    assert "no commit cited" in iirc.ref_changed("docs/a.md", tmp_path)


def test_age_hint_by_kind():
    from datetime import UTC, datetime
    now = datetime(2026, 12, 1, tzinfo=UTC)
    old = {"kind": "environment", "updated": "2026-09-01T00:00:00Z"}
    assert "environment page, 91 days since written" == iirc.age_hint(old, now)
    assert iirc.age_hint({"kind": "procedure", "updated": "2026-09-01T00:00:00Z"}, now) == "procedure page, 91 days since written"
    assert iirc.age_hint({"kind": "finding", "updated": "2026-09-01T00:00:00Z"}, now) is None
    assert iirc.age_hint({"kind": "decision", "updated": "2020-01-01T00:00:00Z"}, now) is None
    verified = {"kind": "environment", "updated": "2026-01-01T00:00:00Z", "verified": "2026-11-20T00:00:00Z"}
    assert iirc.age_hint(verified, now) is None


def test_suspicion_ranks_ref_before_check_before_age(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    import subprocess
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    sha = _repo(tmp_path)
    (tmp_path / "docs" / "a.md").write_text("two\n")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qam", "two"], check=True)
    fm = {"kind": "environment", "updated": "2026-01-01T00:00:00Z", "refs": [f"docs/a.md@{sha}"], "check": "false"}
    iirc.approve_check("false", "t.md")
    signals = iirc.suspicion(fm, tmp_path, run_checks=True, now=datetime(2026, 12, 1, tzinfo=UTC))
    assert [s for s, _ in signals] == ["ref", "check", "age"]
    without = iirc.suspicion(fm, tmp_path, run_checks=False, now=datetime(2026, 12, 1, tzinfo=UTC))
    assert [s for s, _ in without] == ["ref", "age"]
    assert iirc.marker(signals).startswith("  suspect: docs/a.md changed")
    assert "glance: environment page" in iirc.marker(signals)
    assert iirc.marker([]) == ""


def test_run_check_pass_fail_timeout():
    assert iirc.run_check("true") is None
    assert "exit 1" in iirc.run_check("false")
    iirc.CHECK_TIMEOUT = 1
    assert "timed out" in iirc.run_check("sleep 5")
    iirc.CHECK_TIMEOUT = 10


def test_distance_text_handles_substring_fallback():
    assert iirc.distance_text({"distance": 0.3333}) == "distance 0.333"
    assert iirc.distance_text({"distance": None}) == "string match"
    assert iirc.distance_text({}) == "string match"


def test_set_root_and_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert iirc.project_root() == tmp_path.resolve()
    iirc.set_root(tmp_path)
    assert [(s.name, s.kind, s.dir) for s in iirc.STORES] == [("project", "project", tmp_path.resolve() / ".iirc")]
    monkeypatch.delenv("CLAUDE_PROJECT_DIR")
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    assert iirc.project_root() == tmp_path.resolve()


def test_index_carries_format_line_and_check(tmp_path, capsys):
    field = tmp_path / ".iirc"; field.mkdir()
    (field / "index.md").write_text("intro\n")
    iirc.set_root(tmp_path)
    iirc.stamp_index()
    text = (field / "index.md").read_text()
    assert text.endswith("<!-- iirc format 1 -->\n")
    assert iirc.read_format() == 1
    (field / "index.md").write_text(text.replace("format 1", "format 2"))
    with pytest.raises(SystemExit) as e:
        iirc.check_format()
    assert e.value.code == 2 and "newer iirc plugin" in capsys.readouterr().err
    (field / "index.md").write_text("intro only\n")
    assert iirc.read_format() == 0
    iirc.check_format()
    assert iirc.read_format() == 1


def test_init_appends_paragraph_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(iirc.shutil, "which", lambda name: None)
    (tmp_path / "CLAUDE.md").write_text("# Agent\n")
    iirc.main(["init"])
    text = (tmp_path / "CLAUDE.md").read_text()
    assert text.startswith("# Agent\n") and text.count(iirc.CLAUDE_MD_MARK) == 1
    assert (tmp_path / ".iirc" / "index.md").is_file()
    iirc.main(["init"])
    assert (tmp_path / "CLAUDE.md").read_text().count(iirc.CLAUDE_MD_MARK) == 1
    assert "nothing changed" in capsys.readouterr().out


def test_doctor_brief_guides_setup(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    iirc.main(["doctor", "--brief"])
    assert "not set up on this machine" in capsys.readouterr().out
    iirc.main(["setup", "--substring"]); capsys.readouterr()
    iirc.main(["doctor", "--brief"])
    assert "no .iirc/" in capsys.readouterr().out
    monkeypatch.setattr(iirc.shutil, "which", lambda name: None)
    iirc.main(["init"]); capsys.readouterr()
    iirc.main(["doctor", "--brief"])
    out = capsys.readouterr().out
    assert out.startswith("iirc: 0 pages, string search.") and "Persistence:" in out   # no git repo yet
    assert "not at the pin" not in out   # no tool installed: nothing to compare with the pin
    monkeypatch.setattr(iirc.shutil, "which", lambda name: "/usr/bin/memoryfield-tool")
    monkeypatch.setattr(iirc, "installed_rev", lambda: "deadbeef0000")
    iirc.main(["doctor", "--brief"])
    out = capsys.readouterr().out
    assert "memoryfield-tool is not at the pin" in out and "iirc doctor --fix" in out


def test_doctor_health_names_suspects_and_store_state(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setattr(iirc.shutil, "which", lambda name: None)
    iirc.main(["setup", "--substring"]); iirc.main(["init"]); capsys.readouterr()
    monkeypatch.setattr(iirc, "suspicion", lambda fm, *a, **k: [("ref", "x")])
    (tmp_path / ".iirc" / "old.md").write_text("---\ntitle: t\n---\nbody\n")
    iirc.main(["doctor", "--health"])
    out = json.loads(capsys.readouterr().out)
    assert "old.md" in out["suspect"]
    assert [(s["name"], s["kind"], s["unpushed"]) for s in out["stores"]] == [("project", "project", 0)]


def test_git_checks_and_init_staging(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(iirc.shutil, "which", lambda name: None)
    iirc.set_root(tmp_path)
    assert iirc.git_checks()[0][1] == "this directory is a git repository"
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".iirc/\n")
    iirc.main(["init"])
    states = {label: ok for ok, label, _ in iirc.git_checks()}
    assert states[".iirc is ignored by git"] is False
    assert states[".claude/settings.json does not exist"] is False
    (tmp_path / ".gitignore").write_text("")
    (tmp_path / ".claude").mkdir(); (tmp_path / ".claude" / "settings.json").write_text("{}")
    iirc.git_add([".iirc", "CLAUDE.md", ".claude/settings.json"])
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"], check=True)
    assert all(ok for ok, _, _ in iirc.git_checks())


def test_host_candidates_order(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert iirc.host_candidates() == [("http://127.0.0.1:11434", "default")]
    iirc.write_config_file({"embedding_host": "http://frame:11434"})
    assert iirc.host_candidates() == [("http://frame:11434", "iirc setup"), ("http://127.0.0.1:11434", "default")]
    monkeypatch.setenv("OLLAMA_HOST", "other:1")
    assert [c[1] for c in iirc.host_candidates()] == ["OLLAMA_HOST", "iirc setup", "default"]


def test_resolve_host_skips_a_dead_env_host(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("OLLAMA_HOST", "http://dead:11434")
    iirc.write_config_file({"embedding_host": "http://frame:11434"})
    monkeypatch.setattr(iirc, "host_answers", lambda url, timeout=2.0: url == "http://frame:11434")
    iirc._RESOLVED = None
    assert iirc.resolve_host() == ("http://frame:11434", "iirc setup", True)
    iirc._RESOLVED = None
    monkeypatch.setattr(iirc, "host_answers", lambda url, timeout=2.0: False)
    assert iirc.resolve_host() == ("http://dead:11434", "OLLAMA_HOST", False)
    iirc._RESOLVED = None


def test_semantic_search_never_embeds_on_a_dead_host(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(iirc, "host_answers", lambda url, timeout=2.0: False)
    iirc._RESOLVED = None
    called = []
    monkeypatch.setattr(iirc, "tool", lambda *a, **k: called.append(a))
    monkeypatch.setattr(iirc.iirc_embed, "embed", lambda *a, **k: called.append(a))
    assert iirc.semantic_search("anything") == []
    assert called == []
    iirc._RESOLVED = None


def test_setup_writes_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(iirc, "host_answers", lambda base, timeout=2.0, fresh=False: False)
    iirc.main(["setup", "--host", "frame:11434"])
    assert iirc.read_config() == {"semantic": True, "embedding_host": "http://frame:11434", "embedding": {"backend": "ollama", "model": "qwen3-embedding:0.6b"}}
    assert "does not answer yet" in capsys.readouterr().out
    iirc.main(["setup", "--local"])
    assert iirc.read_config()["embedding_host"] == "http://127.0.0.1:11434"
    iirc.main(["setup", "--substring"])
    assert iirc.read_config()["semantic"] is False and iirc.semantic_enabled() is False
    assert iirc.tool_env()["OLLAMA_HOST"] == iirc.NO_EMBEDDING_HOST
    monkeypatch.setenv("OLLAMA_HOST", "x:1")
    assert iirc.semantic_enabled() is True
    monkeypatch.delenv("OLLAMA_HOST")
    with pytest.raises(SystemExit):
        iirc.main(["setup", "--local", "--host", "x"])
    with pytest.raises(SystemExit):
        iirc.main(["setup", "--semantic", "--substring"])


def test_semantic_is_on_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert iirc.semantic_enabled() is True
    iirc.write_config_file({"semantic": False})
    assert iirc.semantic_enabled() is False


def test_merge_results_unions_and_ranks():
    a = [{"filename": "x.md", "summary": "X", "distance": 0.4}, {"filename": "y.md", "summary": "Y", "distance": None}]
    b = [{"filename": "y.md", "summary": "Y", "distance": None}, {"filename": "z.md", "summary": "Z", "distance": 0.2}]
    rows = iirc.merge_results([("one", a), ("two", b)])
    assert [r["filename"] for r in rows] == ["y.md", "z.md", "x.md"]     # matched by both terms first, then by distance
    assert rows[0]["matched"] == ["one", "two"]


def test_query_terms_keeps_identifiers_and_parts():
    assert iirc.query_terms("Why does install fail on a mac with pysqlite3-binary?") == ["install", "fail", "mac", "pysqlite3-binary", "pysqlite3", "binary"]
    assert iirc.query_terms("the memoryfield-tool wrapper") == ["memoryfield-tool", "memoryfield", "tool", "wrapper"]
    assert iirc.query_terms("the of and") == []


def test_string_search_and_hybrid_ranking(tmp_path, monkeypatch):
    field = tmp_path / ".iirc"; field.mkdir()
    (field / "index.md").write_text("intro\n")
    (field / "pysqlite3-install-override.md").write_text("---\ntitle: pysqlite3-binary blocks install\nsummary: the uv override\n---\nx\n")
    (field / "ollama-host-silent-hang.md").write_text("---\ntitle: A silent OLLAMA_HOST hangs the tool\nsummary: probe first\n---\nx\n")
    (field / "unrelated.md").write_text("---\ntitle: Something else\nsummary: nothing here\n---\nx\n")
    iirc.set_root(tmp_path)
    assert iirc.string_search(["intro"]) == []   # index.md is never a result on the string path either
    hits = iirc.string_search(["install", "pysqlite3", "hang"])
    assert {r["filename"]: r["matched"] for r in hits} == {"pysqlite3-install-override.md": ["install", "pysqlite3"], "ollama-host-silent-hang.md": ["hang"]}
    assert next(r for r in hits if r["filename"] == "pysqlite3-install-override.md")["head_terms"] == ["install", "pysqlite3"]   # hyphens are word boundaries
    (field / "verbs.md").write_text("---\ntitle: Something that lets the tool run\nsummary: it adds on top\n---\nx\n")
    verbs = next(r for r in iirc.string_search(["let", "add", "lets"]) if r["filename"] == "verbs.md")
    assert verbs["head_terms"] == ["lets"]   # "let" and "add" are substrings only
    (field / "body-only.md").write_text("---\ntitle: Elsewhere\nsummary: nothing\n---\nthe incident was filed as I113.\n")
    body = iirc.string_search(["i113"])
    assert [r["filename"] for r in body] == ["body-only.md"] and body[0]["head_terms"] == []
    monkeypatch.setattr(iirc, "semantic_enabled", lambda: True)
    monkeypatch.setattr(iirc, "semantic_search", lambda q: [
        {"filename": "unrelated.md", "summary": "nothing here", "distance": 0.30},
        {"filename": "pysqlite3-install-override.md", "summary": "the uv override", "distance": 0.40},
    ])
    rows = iirc.hybrid_search("why does install fail with pysqlite3")
    assert [r["filename"] for r in rows] == ["pysqlite3-install-override.md", "unrelated.md"]   # found by both beats a closer semantic-only hit
    assert rows[0]["via"] == ["semantic", "install", "pysqlite3"]
    monkeypatch.setattr(iirc, "semantic_enabled", lambda: False)
    rows = iirc.hybrid_search("hang")
    assert [r["filename"] for r in rows] == ["ollama-host-silent-hang.md"] and rows[0]["via"] == ["hang"]
    # p5 step 7: four of nine pages say "config", so it is common and lifts no page into the first class
    for n in "abcd":
        (field / f"config-{n}.md").write_text(f"---\ntitle: Config note {n}\nsummary: x\n---\nthe config\n")
    monkeypatch.setattr(iirc, "semantic_enabled", lambda: True)
    monkeypatch.setattr(iirc, "semantic_search", lambda q: [
        {"filename": "config-a.md", "summary": "x", "distance": 0.35},
        {"filename": "unrelated.md", "summary": "nothing here", "distance": 0.20},
    ])
    rows = iirc.hybrid_search("change the config")
    assert [r["filename"] for r in rows][:2] == ["unrelated.md", "config-a.md"]   # closer meaning beats a shared common word


def test_url_refs_are_kept_and_never_checked_in_search(tmp_path):
    assert iirc.fill_ref("https://example.com/x", tmp_path) == "https://example.com/x"
    assert iirc.ref_changed("https://example.com/x", tmp_path) is None
    assert iirc.suspicion({"refs": ["https://example.com/x"]}, tmp_path) == []


def test_url_status_gone_and_unreachable():
    import http.server, threading, socket
    class H(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(404 if self.path == "/gone" else 200); self.end_headers()
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H); port = srv.server_port
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        assert iirc.url_status(f"http://127.0.0.1:{port}/ok") is None
        sig, reason = iirc.url_status(f"http://127.0.0.1:{port}/gone")
        assert sig == "ref" and "gone" in reason
    finally:
        srv.shutdown()
    s = socket.socket(); s.bind(("127.0.0.1", 0)); closed = s.getsockname()[1]; s.close()
    sig, reason = iirc.url_status(f"http://127.0.0.1:{closed}/x", timeout=1.0)
    assert sig == "url" and "could not be reached" in reason
    assert iirc.marker([("url", "x could not be reached")]).startswith("  glance:")


def test_verify_requires_an_approved_check(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    field = tmp_path / ".iirc"; field.mkdir(); iirc.set_root(tmp_path)
    marker = tmp_path / "marker"
    (field / "evil.md").write_text(f"---\ntitle: E\nsummary: e\nkind: finding\ncheck: touch {marker}\n---\nx\n")
    monkeypatch.setattr(iirc, "tool", lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    with pytest.raises(SystemExit):
        iirc.main(["verify", "evil.md"])
    assert not marker.exists() and "not approved" in capsys.readouterr().err
    (field / "bad.md").write_text("---\ntitle: B\nsummary: b\nkind: finding\ncheck: echo x > /tmp/x\n---\nx\n")
    with pytest.raises(SystemExit):
        iirc.main(["verify", "bad.md"])
    assert "not read-only" in capsys.readouterr().err


def _fake_tool(field, calls=None):
    """Stands in for memoryfield-tool: write stores the page in the field= store (else `field`), everything else succeeds silently."""
    def fake(*a, stdin=None, field=None, **k):
        if calls is not None:
            calls.append((a, field))
        target = next((s.dir for s in iirc.STORES if s.field == field), None) if field else None
        if a[0] == "write":
            ((target or field_dir) / a[-1]).write_text(stdin)
        if a[0] == "delete":
            ((target or field_dir) / a[-1]).unlink()
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    field_dir = field
    return fake


def test_verify_clears_a_changed_ref(tmp_path, monkeypatch, capsys):
    """Design test 1: suspect after the cited path changes, clean after verify."""
    import subprocess
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    sha = _repo(tmp_path)
    field = tmp_path / ".iirc"; field.mkdir(); iirc.set_root(tmp_path)
    (field / "cited.md").write_text(f"---\ntitle: C\nsummary: c\nkind: finding\nrefs:\n- docs/a.md@{sha}\n---\nx\n")
    (tmp_path / "docs" / "a.md").write_text("two\n")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qam", "two"], check=True)
    assert [s for s, _ in iirc.suspicion(iirc.page_frontmatter("cited.md"), tmp_path)] == ["ref"]
    monkeypatch.setattr(iirc, "tool", _fake_tool(field))
    monkeypatch.setattr(iirc, "reindex", lambda **k: None)
    iirc.main(["verify", "cited.md"])
    assert "verified cited.md" in capsys.readouterr().out
    fm = iirc.page_frontmatter("cited.md")
    assert fm["verified"] and fm["refs"][0].startswith("docs/a.md@") and not fm["refs"][0].endswith(sha)
    assert iirc.suspicion(fm, tmp_path) == []


def test_pull_prints_the_marker_above_each_page(tmp_path, monkeypatch, capsys):
    import subprocess
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    sha = _repo(tmp_path)
    field = tmp_path / ".iirc"; field.mkdir(); iirc.set_root(tmp_path)
    (field / "cited.md").write_text(f"---\ntitle: C\nsummary: cited page\nkind: finding\nrefs:\n- docs/a.md@{sha}\n---\nx\n")
    (field / "clean.md").write_text("---\ntitle: D\nsummary: clean page\nkind: finding\n---\ny\n")
    (tmp_path / "docs" / "a.md").write_text("two\n")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qam", "two"], check=True)
    monkeypatch.setattr(iirc, "hybrid_search", lambda q: [
        {"filename": "cited.md", "summary": "cited page", "distance": 0.2, "via": ["semantic"]},
        {"filename": "clean.md", "summary": "clean page", "distance": 0.3, "via": ["semantic"]},
    ])
    monkeypatch.setattr(iirc, "tool", lambda *a, **k: pytest.fail("pull renders a page it can parse"))
    iirc.main(["pull", "anything"])
    out = capsys.readouterr().out
    assert out.startswith(iirc.READ_HEAD) and out.endswith(iirc.read_tail([(iirc.STORES[0], "cited.md"), (iirc.STORES[0], "clean.md")]))
    lines = out.splitlines()
    assert lines[1] == "cited.md: C" and lines[2].startswith("suspect: docs/a.md changed") and lines[3] == "x"
    assert lines[4] == f"refs: docs/a.md@{sha}"
    assert lines[6] == "clean.md: D" and lines[7] == "y"
    assert lines[-1].endswith("where PAGE is cited.md or clean.md.")


def test_tool_refuses_an_unpinned_install(monkeypatch, capsys):
    monkeypatch.setattr(iirc, "_PIN_OK", False)
    monkeypatch.setattr(iirc.shutil, "which", lambda name: "/usr/bin/memoryfield-tool")
    monkeypatch.setattr(iirc, "installed_rev", lambda: "deadbeef0000")
    with pytest.raises(SystemExit):
        iirc.tool("validate")
    err = capsys.readouterr().err
    assert "at deadbee" in err and iirc.read_pin()["tool_rev"][:7] in err and "iirc doctor --fix" in err
    monkeypatch.setattr(iirc, "installed_rev", lambda: None)
    with pytest.raises(SystemExit):
        iirc.tool("validate")
    assert "an unknown commit" in capsys.readouterr().err
    monkeypatch.setattr(iirc, "installed_rev", lambda: iirc.read_pin()["tool_rev"])
    ran = []
    monkeypatch.setattr(iirc.subprocess, "run", lambda argv, **k: ran.append(argv) or type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr(iirc, "tool_env", lambda root=None: {})
    iirc.tool("validate")
    assert ran == [["memoryfield-tool", "validate"]] and iirc._PIN_OK


def test_first_token_uses_the_launcher_pair():
    assert iirc.first_token("uv tool install x") == "uv tool"
    assert iirc.first_token("uv --version") == "uv"
    assert iirc.first_token("ls -la") == "ls"
    assert iirc.first_token("git push origin main") == "git push"


def test_recall_filter_treats_distance_less_semantic_as_string_only():
    rows = [{"filename": "x.md", "summary": "X", "distance": None, "via": ["semantic", "pysqlite3"], "rare_terms": ["pysqlite3"], "head_terms": []}]
    assert [r["filename"] for r in iirc.recall_filter(rows)] == ["x.md"]


def test_recall_worthy_long_prompt_starting_with_no():
    assert iirc.recall_worthy("No, don't do that; instead debug why memoryfield-tool cannot reach the ollama host on port 11434 and fix it")
    assert not iirc.recall_worthy("No thanks, that is fine as it is, leave it there")


def test_recall_skips_machine_prompts_and_searches_the_person_s_words(tmp_path, monkeypatch, capsys):
    handback = '<agent-message from="a1b2">\n[Subagent hand-back] The report follows: wrote 14 lines about pysqlite3-binary\n</agent-message>'
    done = '<task-notification>\n<task-id>x</task-id>\n<status>completed</status>\n</task-notification>'
    reminder = '<system-reminder>\nAnother session sent a message about pysqlite3-binary\n</system-reminder>'
    assert iirc.skip_reason(handback) == "machine"
    assert iirc.skip_reason(done + "\n" + reminder) == "machine"
    assert iirc.skip_reason('<agent-message from="a">cut off, never closed') == "machine"
    mixed = reminder + "\nwhy does uv tool install memoryfield-tool fail on this mac"
    assert iirc.skip_reason(mixed) is None
    assert iirc.person_text(mixed) == "why does uv tool install memoryfield-tool fail on this mac"
    assert iirc.person_text("plain <b>html</b> stays") == "plain <b>html</b> stays"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    field = tmp_path / ".iirc"; field.mkdir()
    (field / "pysqlite3-install-override.md").write_text("---\ntitle: pysqlite3-binary blocks install\nsummary: the uv override\ntopics: [install]\nkind: environment\n---\nx\n")
    iirc.write_config_file({"semantic": False})
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": handback})))
    iirc.main(["recall"])
    assert capsys.readouterr().out == ""                  # the hand-back names pysqlite3-binary, and recall stays silent
    assert iirc.read_log()[-1]["reason"] == "machine"


def test_guard_asks_for_approve_too():
    import json, subprocess
    shim = ROOT / "scripts" / "guard.sh"
    def run(cmd):
        return subprocess.run(["sh", str(shim)], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": "/tmp/iirc-doubt-notes"}), capture_output=True, text=True)
    assert "ask" in run("iirc approve x.md").stdout
    assert run("ls").stdout == ""               # a cwd containing the words does not trigger it


def test_guard_denies_a_raw_read_of_a_page():
    import json, subprocess
    shim = ROOT / "scripts" / "guard.sh"
    def run(cmd):
        return subprocess.run(["sh", str(shim)], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}), capture_output=True, text=True)
    def read(path):
        return subprocess.run(["sh", str(shim)], input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": path}}), capture_output=True, text=True)
    for path in ("/repo/.iirc/a-page.md", ".iirc/a-page.md"):
        out = json.loads(read(path).stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", path
        assert "iirc read a-page.md" in out["hookSpecificOutput"]["permissionDecisionReason"]
    for path in ("/repo/.iirc/index.md", "/repo/docs/iirc/notes.md", "/repo/README.md"):
        assert read(path).stdout == "", path
    for cmd in ("cat .iirc/ollama-host.md", "cat /repo/.iirc/a-page.md | head", "head -20 .iirc/a-page.md", "sed -n 1,40p .iirc/a-page.md",
                "iirc search x 2>&1 || true; echo ---; cat .iirc/a-page.md; cat Makefile", "ls && cat .iirc/a-page.md", "(cat .iirc/a-page.md)", "ls\\ncat .iirc/a-page.md"):
        out = json.loads(run(cmd).stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", cmd
        assert "iirc read" in out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "iirc doctor --fix" in out["hookSpecificOutput"]["permissionDecisionReason"]
    for cmd in ("cat .iirc/index.md", "iirc read a-page.md", "cat README.md", "ls .iirc", "cat >> .iirc/a-page.md <<EOF"):
        assert run(cmd).stdout == "", cmd


def test_guard_asks_only_for_network_doubt():
    import json, subprocess
    shim = ROOT / "scripts" / "guard.sh"
    def run(cmd):
        return subprocess.run(["sh", str(shim)], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}), capture_output=True, text=True)
    assert run("iirc doubt").stdout == ""
    assert run("git status").stdout == ""
    out = json.loads(run("iirc doubt --network").stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_recall_gates_and_filter(monkeypatch):
    monkeypatch.setattr(iirc, "RECALL", {"semantic_only": 0.28, "both": 0.34})   # the fixtures sit around these knobs, not the defaults
    assert not iirc.recall_worthy("yes")
    assert not iirc.recall_worthy("Yes, it is completed. Your suggested timebox works fine by me.")
    assert not iirc.recall_worthy("3> agree, and the second one too, please go ahead")
    assert not iirc.recall_worthy("/plugin install iirc@dokidlc and then something long enough")
    assert iirc.recall_worthy("why does installing memoryfield-tool fail on this mac")
    rows = [
        {"filename": "both-rare.md", "summary": "B", "distance": 0.33, "via": ["semantic", "pysqlite3"], "rare_terms": ["pysqlite3"], "head_terms": []},
        {"filename": "both-common.md", "summary": "C", "distance": 0.33, "via": ["semantic", "tool"], "rare_terms": [], "head_terms": ["tool"]},
        {"filename": "both-weak.md", "summary": "W", "distance": 0.33, "via": ["semantic", "commit"], "rare_terms": ["commit"], "head_terms": []},
        {"filename": "both-far.md", "summary": "F", "distance": 0.36, "via": ["semantic", "pysqlite3"], "rare_terms": ["pysqlite3"], "head_terms": []},
        {"filename": "close.md", "summary": "C", "distance": 0.27, "via": ["semantic"]},
        {"filename": "near.md", "summary": "N", "distance": 0.31, "via": ["semantic"]},
        {"filename": "ident.md", "summary": "I", "distance": None, "via": ["192.168.1.10"], "rare_terms": ["192.168.1.10"], "head_terms": []},
        {"filename": "titled.md", "summary": "T", "distance": None, "via": ["ollama"], "rare_terms": ["ollama"], "head_terms": ["ollama"]},
        {"filename": "short-verb.md", "summary": "S", "distance": None, "via": ["lets"], "rare_terms": ["lets"], "head_terms": ["lets"]},
        {"filename": "word.md", "summary": "W", "distance": None, "via": ["section"], "rare_terms": ["section"], "head_terms": []},
    ]
    assert [r["filename"] for r in iirc.recall_filter(rows)] == ["both-rare.md", "close.md", "ident.md"]
    # a page that semantic search did not return passes on an identifier, never on a word in its title
    assert [r["filename"] for r in iirc.recall_filter(rows[4:])] == ["close.md", "ident.md"]


def test_recall_line_names_read_commands_and_is_bounded(tmp_path, monkeypatch):
    iirc.set_root(tmp_path); (tmp_path / ".iirc").mkdir()
    rows = [{"filename": f"page-{i}.md", "summary": "s" * 150, "distance": 0.2, "via": ["semantic"]} for i in range(3)]
    line = iirc.recall_line(rows)
    assert line.startswith("iirc: ") and "`iirc read page-0.md`" in line
    assert len(line.encode()) <= iirc.recall_max_bytes()
    assert "page-2.md" not in line or line.count("`iirc read") == 3   # whole entries dropped, never cut
    assert iirc.recall_line([]) == ""


def test_stats_session_counts_suggested_pages_used(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s6"); iirc.set_root(tmp_path)
    iirc.log_event("recall", hits=2, pages=["a.md", "b.md"], via="prompt"); iirc.log_event("recall", hits=1, pages=["c.md"], via="failure")
    iirc.log_event("read", pages=["b.md", "z.md"])
    iirc.main(["stats", "--session", "s6"])
    out = json.loads(capsys.readouterr().out)
    assert out["suggested"] == ["a.md", "b.md", "c.md"] and out["used"] == ["b.md"]
    assert out["missed"] == [["a.md", 1], ["c.md", 1]]


def test_stats_session_lists_missed_pages_most_suggested_first(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s7"); iirc.set_root(tmp_path)
    for pages in (["a.md", "b.md"], ["b.md"], ["b.md", "c.md"]):
        iirc.log_event("recall", hits=len(pages), pages=pages, via="prompt")
    iirc.log_event("read", pages=["c.md"])
    iirc.main(["stats", "--session", "s7"])
    assert json.loads(capsys.readouterr().out)["missed"] == [["b.md", 3], ["a.md", 1]]


def test_stats_session_averages_match_for_read_and_unread(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s8"); iirc.set_root(tmp_path)
    iirc.log_event("recall", hits=3, pages=["a.md", "b.md", "c.md"], scores=["80% match, meaning", "60% match, meaning+term", "term match"], via="prompt")
    iirc.log_event("recall", hits=1, pages=["b.md"], scores=["70% match, meaning"], via="prompt")
    iirc.log_event("read", pages=["a.md"])
    iirc.main(["stats", "--session", "s8"])
    assert json.loads(capsys.readouterr().out)["match"] == {"all": 70, "read": 80, "unread": 65}


def test_a_term_match_needs_an_identifier():
    word = {"filename": "a.md", "summary": "s", "via": ["plain"], "rare_terms": ["without"], "head_terms": ["without"]}
    ident = {"filename": "b.md", "summary": "s", "via": ["2.1.290"], "rare_terms": ["2.1.290"], "head_terms": []}
    assert [r["filename"] for r in iirc.recall_filter([word, ident])] == ["b.md"]


def test_recall_line_shows_the_match_and_its_rule():
    assert iirc.match_text({"distance": 0.31, "rule": "meaning+term"}) == "69% match, meaning+term"
    assert iirc.match_text({"distance": 0.2, "rule": "meaning"}) == "80% match, meaning"
    assert iirc.match_text({"rule": "term"}) == "term match"
    rows = iirc.recall_filter([{"filename": "a.md", "summary": "s", "distance": 0.2, "via": ["semantic"]}])
    assert rows[0]["rule"] == "meaning"


def test_max_suggested_sets_how_many_pages_recall_suggests(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    iirc.set_root(tmp_path); iirc.write_config_file({"semantic": True, "embedding_host": "http://h:1"})
    assert iirc.max_suggested() == 3
    rows = [{"filename": f"p{i}.md", "summary": "s", "distance": 0.1, "via": ["semantic"]} for i in range(6)]
    assert len(iirc.recall_filter(rows)) == 3
    iirc.main(["max-suggested", "5"])
    assert "suggests up to 5 pages" in capsys.readouterr().out
    assert iirc.max_suggested() == 5 and len(iirc.recall_filter(rows)) == 5
    assert iirc.read_config()["embedding_host"] == "http://h:1"   # the other settings stay
    iirc.main(["max-suggested"])
    assert "suggests up to 5 pages" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        iirc.main(["max-suggested", "0"])
    iirc.write_config_file({"max_suggested": "lots"})
    assert iirc.max_suggested() == 3


def test_clip_cuts_at_a_word_boundary():
    summary = "Hook lines arrive as session.append hook-context rows; a Bash call in a collapsed ToolGroup draws no ToolUse row"
    assert iirc.clip(summary, 90) == "Hook lines arrive as session.append hook-context rows; a Bash call in a collapsed…"
    assert len(iirc.clip(summary, 90)) <= 90
    assert iirc.clip("short", 90) == "short"
    assert iirc.clip("x" * 120, 90) == "x" * 89 + "…"   # one long word is cut where it must be


def test_recall_hook_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    field = tmp_path / ".iirc"; field.mkdir()
    (field / "pysqlite3-install-override.md").write_text("---\ntitle: pysqlite3-binary blocks install\nsummary: the uv override\ntopics: [install]\nkind: environment\n---\nx\n")
    iirc.write_config_file({"semantic": False})
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": "why does uv tool install memoryfield-tool fail with pysqlite3-binary"})))
    iirc.main(["recall"])
    out = capsys.readouterr().out
    assert "`iirc read pysqlite3-install-override.md`" in out
    assert "may apply. Read a page whose summary bears on this task; skip the rest: " in out
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": "yes"})))
    iirc.main(["recall"]); assert capsys.readouterr().out == ""
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s2")   # in s1 the page is a repeat now
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "uv tool install memoryfield-tool"}, "error": "Exit code 1\nno wheels for pysqlite3-binary"})))
    iirc.main(["recall", "--failure"])
    out = json.loads(capsys.readouterr().out)
    assert "pysqlite3-install-override.md" in out["hookSpecificOutput"]["additionalContext"]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls /nope"}, "error": "Exit code 2"})))
    iirc.main(["recall", "--failure"])
    assert capsys.readouterr().out == ""          # nothing but the exit code: stay silent
    rows = iirc.read_log()
    assert [r["cmd"] for r in rows] == ["recall", "skipped", "failure", "recall", "failure"]
    assert "query" not in rows[0]                 # prompt text is not logged
    assert rows[1]["reason"] == "short" and len(rows[1]["prompt_hash"]) == 16
    first = rows[0]
    assert first["prompt_hash"] == iirc.prompt_hash("why does uv tool install memoryfield-tool fail with pysqlite3-binary")
    # every candidate is in the eval file, keyed to its recall
    evals = [json.loads(line) for f in sorted((tmp_path / "st" / "dokidlc-iirc").glob("eval-*.jsonl")) for line in f.read_text().splitlines()]
    mine = [e for e in evals if e["recall_id"] == first["recall_id"]]
    assert mine and mine[0]["page"] == "pysqlite3-install-override.md" and mine[0]["verdict"] == "passed" and mine[0]["rule"] == "term"
    assert {e["via"] for e in evals} == {"prompt", "failure"}
    # the prompt's excerpt, in the session's own file, never in the log
    kept = [json.loads(line) for f in sorted((tmp_path / "st" / "dokidlc-iirc" / "prompts").glob("*.jsonl")) for line in f.read_text().splitlines()]
    assert [k.get("skipped") for k in kept] == [None, "short", None] and kept[0]["recall_id"] == first["recall_id"]
    assert kept[0]["excerpt"].startswith("why does uv tool install")
    # the failure's command and error, for tune once the transcript is gone
    assert (kept[2]["excerpt"], kept[2]["error"]) == ("uv tool install memoryfield-tool", "no wheels for pysqlite3-binary")


def test_show_hooks_shows_each_hook_line_to_the_user(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s5")
    monkeypatch.setattr(iirc.shutil, "which", lambda name: None)
    field = tmp_path / ".iirc"; field.mkdir()
    (field / "pysqlite3-install-override.md").write_text("---\ntitle: pysqlite3-binary blocks install\nsummary: the uv override\ntopics: [install]\nkind: environment\n---\nx\n")
    (tmp_path / ".claude").mkdir(); (tmp_path / ".claude" / "iirc.toml").write_text("show_hooks = true\n")
    iirc.write_config_file({"semantic": False})
    def run(argv, payload):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload))); iirc.main(argv); return capsys.readouterr().out
    out = json.loads(run(["recall"], {"prompt": "why does uv tool install memoryfield-tool fail with pysqlite3-binary"}))
    assert out["systemMessage"] == out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit" and "pysqlite3-install-override.md" in out["systemMessage"]
    out = json.loads(run(["doctor", "--brief", "--hook"], {"hook_event_name": "SessionStart", "session_id": "s5"}))
    assert out["systemMessage"].startswith("iirc: 1 page") and out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s6")   # in s5 the page is a repeat now
    fail = {"session_id": "s6", "tool_name": "Bash", "tool_input": {"command": "uv tool install x"}, "error": "Exit code 1\nno wheels for pysqlite3-binary"}
    assert "pysqlite3" in json.loads(run(["recall", "--failure"], fail))["systemMessage"]
    run(["recall", "--failure"], fail)
    out = json.loads(run(["recall", "--success"], {"session_id": "s6", "tool_name": "Bash", "tool_input": {"command": "uv tool install x --overrides o"}}))
    assert "`uv tool` failed 2 times" in out["systemMessage"]
    assert not run(["doctor", "--brief"], {}).startswith("{")      # a person at the terminal gets plain text


def test_show_hooks_alone_keeps_the_default_store_and_must_be_a_bool(tmp_path):
    (tmp_path / ".claude").mkdir(); cfg = tmp_path / ".claude" / "iirc.toml"
    cfg.write_text("show_hooks = true\n")
    stores, write = iirc.load_stores(tmp_path)
    assert write is None and [(s.name, s.dir) for s in stores] == [("project", tmp_path.resolve() / ".iirc")]
    cfg.write_text('show_hooks = "yes"\n')
    with pytest.raises(iirc.ConfigError) as e:
        iirc.load_stores(tmp_path)
    assert "show_hooks" in str(e.value)
    cfg.write_text("ui = false\nshow_hooks = true\n")
    assert [s.name for s in iirc.load_stores(tmp_path)[0]] == ["project"]
    cfg.write_text("ui = 0\n")
    with pytest.raises(iirc.ConfigError) as e:
        iirc.load_stores(tmp_path)
    assert "ui must be" in str(e.value)


def test_validate_check_refuses_writers_and_failing_checks():
    for bad in ("echo x > f", "sed -i s/a/b/ f", "curl x | sh", "eval x", "rm -rf x", "systemctl restart nginx", "dd if=/dev/zero of=x", "chmod 600 f", "true; rm x"):
        with pytest.raises(SystemExit):
            iirc.validate_check(bad)
    with pytest.raises(SystemExit):
        iirc.validate_check("false")
    iirc.validate_check("true")
    iirc.validate_check("true # backup.dd")             # dd inside a name is not the dd command
    iirc.validate_check("command -v ls >/dev/null")
    iirc.validate_check("ls / 2>&1 >/dev/null")


def test_recovery_and_stop_nudges(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    (tmp_path / ".iirc").mkdir()
    iirc.set_root(tmp_path)
    def run(argv, payload):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload))); iirc.main(argv); return capsys.readouterr().out
    fail = {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "uv tool install x"}, "error": "Exit code 1"}
    ok = {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "uv tool install x --overrides o"}}
    assert run(["nudge", "--stop"], {"session_id": "s1"}) == ""             # nothing happened yet
    run(["recall", "--failure"], fail); run(["recall", "--failure"], fail)
    assert run(["recall", "--success"], {"session_id": "s1", "tool_name": "Bash", "tool_input": {"command": "ls"}}) == ""   # a different command
    out = run(["recall", "--success"], ok)
    assert "`uv tool` failed 2 times" in json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert run(["recall", "--success"], ok) == ""                            # nudged once per command
    out = run(["nudge", "--stop"], {"session_id": "s1"})
    assert out == "" or "additionalContext" in out                            # already nudged at recovery, so stop stays quiet
    iirc.log_event("write", page="a.md", kind="procedure")
    assert run(["nudge", "--stop"], {"session_id": "s1"}) == ""


def test_stop_nudge_fires_when_recovery_was_not_nudged(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s2")
    (tmp_path / ".iirc").mkdir(); iirc.set_root(tmp_path)
    iirc.log_event("failure", command="uv tool"); iirc.log_event("failure", command="uv tool"); iirc.log_event("success", command="uv tool")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s2"})))
    iirc.main(["nudge", "--stop"])
    out = json.loads(capsys.readouterr().out)
    assert "say so and stop" in out["hookSpecificOutput"]["additionalContext"]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s2"})))
    iirc.main(["nudge", "--stop"]); assert capsys.readouterr().out == ""


def test_brief_channels(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s3")
    monkeypatch.setattr(iirc.shutil, "which", lambda name: None)
    iirc.write_config_file({"semantic": False}); iirc.set_root(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}")); iirc.main(["init"]); capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SubagentStart", "session_id": "s3"})))
    iirc.main(["doctor", "--brief", "--hook"])
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "SubagentStart" and "iirc: 0 pages" in out["hookSpecificOutput"]["additionalContext"]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart", "source": "compact", "session_id": "s3"})))
    iirc.main(["doctor", "--brief", "--hook"])
    assert "just compacted" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart", "source": "startup", "session_id": "s3"})))
    iirc.main(["doctor", "--brief", "--hook"])
    assert "just compacted" not in capsys.readouterr().out
    starts = [r for r in iirc.read_log(session="s3") if r["cmd"] == "start"]
    assert [r["source"] for r in starts] == ["compact", "startup"]   # SubagentStart logs no start
    assert starts[0]["knobs"] == {"semantic_only": 0.28, "both": 0.38} and starts[0]["max_suggested"] == 3 and starts[0]["page_count"] == 0
    # semantic mode probes the host, and the host's source must not replace the hook's
    iirc.write_config_file({"semantic": True})
    monkeypatch.setattr(iirc, "resolve_host", lambda: ("http://127.0.0.1:11434", "config", True))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart", "source": "compact", "session_id": "s3"})))
    iirc.main(["doctor", "--brief", "--hook"])
    assert "just compacted" in capsys.readouterr().out


def test_snapshot_logs_the_session_with_its_conditions(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); iirc.set_root(tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s9")
    iirc.log_event("recall", hits=2, pages=["a.md", "b.md"], scores=["70% match, meaning", "66% match, meaning"], via="prompt")
    iirc.log_event("read", pages=["a.md", "z.md"]); iirc.log_event("verify", page="a.md"); iirc.log_event("skipped", reason="short")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionEnd", "reason": "clear", "session_id": "s9", "transcript_path": "/t/s9.jsonl"})))
    iirc.main(["stats", "--snapshot", "--hook"])
    assert capsys.readouterr().out == ""
    row = [r for r in iirc.read_log(session="s9") if r["cmd"] == "session"][-1]
    assert (row["trigger"], row["reason"], row["transcript"]) == ("SessionEnd", "clear", "/t/s9.jsonl")
    assert row["used"] == ["a.md"] and row["missed"] == [["b.md", 1]] and row["read_unsuggested"] == ["z.md"]
    assert row["suggested_verified"] == ["a.md"] and row["skipped"] == 1 and row["recalls_with_pages"] == 1
    assert row["knobs"] == {"semantic_only": 0.28, "both": 0.38} and "commit" in row and row["mode"] in ("semantic", "string")


def test_stats(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s4"); iirc.set_root(tmp_path)
    iirc.log_event("search", query="q", hits=1, pages=["a.md"]); iirc.log_event("read", pages=["a.md"]); iirc.log_event("write", page="a.md", kind="finding")
    iirc.main(["stats"])
    out = capsys.readouterr().out
    assert "1 session" in out and "read after a search or recall named it: 1/1" in out


def test_stats_session_counts_distinct_pages_read_and_written(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s5"); iirc.set_root(tmp_path)
    iirc.log_event("read", pages=["a.md", "b.md"]); iirc.log_event("pull", query="q", hits=2, pages=["b.md", "c.md"])
    iirc.log_event("search", query="q", hits=1, pages=["d.md"])
    iirc.log_event("write", page="f.md", kind="finding"); iirc.log_event("write", page="f.md", kind="finding")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "other"); iirc.log_event("read", pages=["e.md"])
    iirc.main(["stats", "--session", "s5"])
    assert json.loads(capsys.readouterr().out) == {"session": "s5", "read": ["a.md", "b.md", "c.md"], "written": ["f.md"], "suggested": [], "used": [], "missed": [], "match": {"all": None, "read": None, "unread": None}, "timeouts": 0, "gone": ["f.md"]}
    iirc.main(["stats", "--session"])
    assert json.loads(capsys.readouterr().out)["read"] == ["e.md"]


def test_approved_checks_gate_doubt(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st")); iirc.set_root(tmp_path)
    fm = {"kind": "finding", "check": "true", "updated": "2026-09-04T00:00:00Z"}
    sig = iirc.suspicion(fm, tmp_path, run_checks=True)
    assert sig and sig[0][0] == "unapproved"
    iirc.approve_check("true", "x.md")
    assert iirc.suspicion(fm, tmp_path, run_checks=True) == []
    iirc.approve_check("false", "y.md")
    assert iirc.suspicion({"kind": "finding", "check": "false"}, tmp_path, run_checks=True)[0][0] == "check"


def test_terms_keep_dotted_numbers_whole():
    assert iirc.query_terms("the NAS at 192.168.1.10 runs 5.2.9 and ollama-host-3") == ["nas", "192.168.1.10", "runs", "5.2.9", "ollama-host-3", "ollama", "host"]


def test_doctor_brief_returns_with_stdin_held_open(tmp_path):
    """A script that inherits an open pipe must not hang: without --hook the command never reads stdin."""
    import os, select, subprocess
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path / "cfg"), XDG_STATE_HOME=str(tmp_path / "st"), CLAUDE_PROJECT_DIR=str(tmp_path))
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    proc = subprocess.Popen([str(ROOT / "bin" / "iirc"), "doctor", "--brief"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True)
    try:
        ready, _, _ = select.select([proc.stdout], [], [], 60)   # stdin stays open the whole time
        assert ready, "doctor --brief did not print within 60 seconds with stdin held open"
        assert "iirc: not set up" in proc.stdout.readline()
    finally:
        proc.kill()


# --- stores -------------------------------------------------------------------


def _two_stores(tmp_path, monkeypatch, write=None, remote_url="https://example.com/agent-iirc.git"):
    """A project store at .iirc and a remote store whose clone directory exists (no git needed)."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    (tmp_path / ".claude").mkdir(exist_ok=True)
    head = f'write = "{write}"\n' if write else ""
    (tmp_path / ".claude" / "iirc.toml").write_text(
        head + '[stores.project]\nkind = "project"\npath = ".iirc"\n\n[stores.agent]\nkind = "remote"\n'
        f'url = "{remote_url}"\n')
    (tmp_path / ".iirc").mkdir(exist_ok=True)
    iirc.set_root(tmp_path)
    agent = iirc.store_named("agent")
    agent.dir.mkdir(parents=True, exist_ok=True)
    return iirc.store_named("project"), agent


def _page(store_dir, name, summary="s", extra=""):
    (store_dir / name).write_text(f"---\ntitle: T\nsummary: {summary}\ntopics: [t]\nkind: finding\n{extra}---\nbody\n")


def test_load_stores_defaults_to_one_project_store(tmp_path):
    stores, write = iirc.load_stores(tmp_path)
    assert write is None and len(stores) == 1
    s = stores[0]
    assert (s.name, s.kind, s.dir, s.field) == ("project", "project", tmp_path.resolve() / ".iirc", iirc.field_name(tmp_path))


def test_load_stores_reads_project_and_remote(tmp_path, monkeypatch):
    project, agent = _two_stores(tmp_path, monkeypatch, write="agent")
    assert iirc.WRITE_DEFAULT == "agent" and [s.name for s in iirc.STORES] == ["project", "agent"]
    assert agent.kind == "remote" and agent.url == "https://example.com/agent-iirc.git"
    assert agent.dir.parent == tmp_path / "data" / "dokidlc-iirc" / "stores"
    assert iirc.re.fullmatch(r"agent-[0-9a-f]{8}", agent.dir.name) and agent.field == agent.dir.name
    assert project.field == iirc.field_name(tmp_path)


def test_load_stores_rejects_bad_config(tmp_path):
    (tmp_path / ".claude").mkdir()
    cfg = tmp_path / ".claude" / "iirc.toml"
    bad = [
        '[stores.agent-]\nkind = "remote"\nurl = "u"\n',
        '[stores.a--b]\nkind = "remote"\nurl = "u"\n',
        '[stores.project]\nkind = "project"\npath = "/abs"\n',
        '[stores.agent]\nkind = "remote"\n',
        'write = "nope"\n[stores.project]\nkind = "project"\n',
        '[stores.one]\nkind = "remote"\nurl = "u"\n[stores.two]\nkind = "remote"\nurl = "v"\n',
        'not toml [',
    ]
    for text in bad:
        cfg.write_text(text)
        with pytest.raises(iirc.ConfigError) as e:
            iirc.load_stores(tmp_path)
        assert ".claude/iirc.toml" in str(e.value), text


def test_config_error_kills_commands_and_silences_hooks(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    (tmp_path / ".claude").mkdir(); (tmp_path / ".claude" / "iirc.toml").write_text("not toml [")
    with pytest.raises(SystemExit):
        iirc.main(["search", "x"])
    assert ".claude/iirc.toml" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": "a prompt long enough to be worth a recall search here"})))
    iirc.main(["recall"])
    assert capsys.readouterr() == ("", "")
    # the brief says the hooks are off and names the fix, so the hint row turns red
    iirc.main(["doctor", "--brief"])
    out = capsys.readouterr().out
    assert out.startswith("iirc: hooks off, .claude/iirc.toml") and "`iirc doctor`" in out
    with pytest.raises(SystemExit):
        iirc.main(["doctor"])
    assert "FAIL .claude/iirc.toml loads, so the hooks run" in capsys.readouterr().out


def test_doctor_fix_comments_out_a_bad_knob(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    (tmp_path / ".claude").mkdir()
    toml = tmp_path / ".claude" / "iirc.toml"
    toml.write_text("ui = true\n\n[recall.nomic-embed-text]\nsemantic_only = 0.9   # too loose\nboth = 0.34\n")
    iirc.main(["doctor", "--brief"])
    assert "`iirc doctor --fix`" in capsys.readouterr().out
    monkeypatch.setattr(iirc, "install_tool", lambda pin: False)   # stop before the network checks
    monkeypatch.setattr(iirc.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit):
        iirc.main(["doctor", "--fix"])
    out = capsys.readouterr().out
    assert "commented out `semantic_only = 0.9   # too loose`" in out and "ok  .claude/iirc.toml loads" in out
    assert "# semantic_only = 0.9   # too loose  # iirc doctor --fix: must be a number from 0.1 to 0.6" in toml.read_text()
    assert "ui = true" in toml.read_text() and "\nboth = 0.34" in toml.read_text()
    iirc.set_root(tmp_path)
    assert iirc.CONFIG_ERROR is None and iirc.RECALL["semantic_only"] == 0.28
    # a broken store table is the person's to fix: doctor names it and does not touch the file
    toml.write_text("[stores.x]\nkind = \"nope\"\n")
    iirc.set_root(tmp_path)
    assert not iirc.knob_error_only()


def test_a_killed_recall_is_logged_as_a_timeout_at_the_next(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s11"); iirc.set_root(tmp_path)
    monkeypatch.setattr(iirc, "hybrid_search", lambda q: [])
    marker = iirc.inflight_marker(); marker.parent.mkdir(parents=True); marker.write_text("2026-10-09T00:00:00Z")   # as a killed recall leaves it
    iirc.run_recall("a query long enough to search", "prompt", {})
    rows = iirc.read_log(session="s11")
    assert [r["cmd"] for r in rows] == ["timeout", "recall"] and rows[0]["started"] == "2026-10-09T00:00:00Z"
    assert not marker.exists()                       # a finished recall removes its marker
    assert iirc.session_summary("s11")["timeouts"] == 1


def test_config_text_lists_every_store(tmp_path, monkeypatch):
    project, agent = _two_stores(tmp_path, monkeypatch)
    text = iirc.config_text(tmp_path)
    assert f"[memoryfields.{project.field}]" in text and f"[memoryfields.{agent.field}]" in text
    assert f'location = "{agent.dir.resolve()}"' in text


def test_resolve_page_bare_prefixed_and_ambiguous(tmp_path, monkeypatch, capsys):
    project, agent = _two_stores(tmp_path, monkeypatch)
    _page(project.dir, "only-here.md"); _page(agent.dir, "both.md"); _page(project.dir, "both.md")
    assert iirc.resolve_page("only-here.md") == (project, "only-here.md")
    assert iirc.resolve_page("agent/both.md") == (agent, "both.md")
    with pytest.raises(SystemExit):
        iirc.resolve_page("both.md")
    err = capsys.readouterr().err
    assert "project/both.md" in err and "agent/both.md" in err
    with pytest.raises(SystemExit):
        iirc.resolve_page("nostore/x.md")


def test_write_store_order(tmp_path, monkeypatch):
    project, agent = _two_stores(tmp_path, monkeypatch)
    assert iirc.write_store("agent") == agent
    assert iirc.write_store(None) == project                    # no write key: the project store
    _two_stores(tmp_path, monkeypatch, write="agent")
    assert iirc.write_store(None) == iirc.store_named("agent")
    (tmp_path / ".claude" / "iirc.toml").write_text('[stores.solo]\nkind = "remote"\nurl = "u"\n')
    iirc.set_root(tmp_path)
    assert iirc.write_store(None).name == "solo"               # the only store


def test_write_refuses_a_name_in_another_store(tmp_path, monkeypatch, capsys):
    import io
    project, agent = _two_stores(tmp_path, monkeypatch)
    _page(agent.dir, "taken.md")
    monkeypatch.setattr(iirc, "tool", _fake_tool(project.dir))
    monkeypatch.setattr(iirc, "reindex", lambda **k: None)
    argv = ["write", "taken.md", "--title", "T", "--summary", "s", "--topics", "t", "--kind", "finding"]
    monkeypatch.setattr("sys.stdin", io.StringIO("x\n\n## Sources\n\n- y\n"))
    with pytest.raises(SystemExit):
        iirc.main(argv)
    assert "already exists in store agent" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO("x\n\n## Sources\n\n- y\n"))
    iirc.main(argv + ["--store", "project"])
    assert (project.dir / "taken.md").is_file()


def test_read_and_pull_pass_the_field(tmp_path, monkeypatch, capsys):
    project, agent = _two_stores(tmp_path, monkeypatch)
    _page(project.dir, "p.md"); _page(agent.dir, "a.md")
    calls = []
    (project.dir / "raw.md").write_text("no frontmatter\n"); (agent.dir / "raw.md").write_text("no frontmatter\n")
    monkeypatch.setattr(iirc, "tool", _fake_tool(project.dir, calls))
    iirc.main(["read", "p.md", "agent/a.md"])
    out = capsys.readouterr().out
    assert calls == [] and "project/p.md: T\n" in out and "agent/a.md: T\n" in out
    # a page the wrapper cannot parse goes to the tool, with its store's field
    iirc.main(["read", "project/raw.md", "agent/raw.md"])
    assert [(a[0], a[-1], f) for a, f in calls] == [("read", "raw.md", project.field), ("read", "raw.md", agent.field)]
    calls.clear(); capsys.readouterr()
    monkeypatch.setattr(iirc, "hybrid_search", lambda q: [{"filename": "raw.md", "store": "agent", "summary": "s", "distance": 0.2, "via": ["semantic"]}])
    iirc.main(["pull", "x"])
    assert calls == [(("read", "--no-line-numbers", "raw.md"), agent.field)]


def test_search_prefixes_store_with_two_stores(tmp_path, monkeypatch, capsys):
    project, agent = _two_stores(tmp_path, monkeypatch)
    _page(project.dir, "ollama-p.md", "ollama in project"); _page(agent.dir, "ollama-a.md", "ollama in agent")
    iirc.write_config_file({"semantic": False})
    iirc.main(["search", "ollama"])
    lines = capsys.readouterr().out.splitlines()
    assert sorted(line.split(":")[0] for line in lines) == ["agent/ollama-a.md", "project/ollama-p.md"]
    iirc.main(["search", "--json", "ollama"])
    rows = json.loads(capsys.readouterr().out)
    assert sorted((r["store"], r["filename"]) for r in rows) == [("agent", "ollama-a.md"), ("project", "ollama-p.md")]
    (tmp_path / ".claude" / "iirc.toml").unlink(); iirc.set_root(tmp_path)
    iirc.main(["search", "ollama"])
    assert capsys.readouterr().out.startswith("ollama-p.md: ")      # one store: no prefix


# --- auto commit --------------------------------------------------------------


def _git(repo, *args):
    import subprocess
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def _project(tmp_path, monkeypatch):
    """A git repository with a committed .iirc/index.md, isolated from the user's git config."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null"); monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "t"); monkeypatch.setenv(f"GIT_{who}_EMAIL", "t@t")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    _repo(tmp_path)
    field = tmp_path / ".iirc"; field.mkdir()
    (field / "index.md").write_text(iirc.INDEX_TEMPLATE)
    _git(tmp_path, "add", ".iirc"); _git(tmp_path, "commit", "-qm", "iirc")
    iirc.set_root(tmp_path)
    monkeypatch.setattr(iirc, "tool", _fake_tool(field))
    monkeypatch.setattr(iirc, "reindex", lambda **k: None)
    return field


def _write(monkeypatch, name, *extra):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("x\n\n## Sources\n\n- y\n"))
    iirc.main(["write", name, "--title", "T", "--summary", "s", "--topics", "t", "--kind", "finding", *extra])


def test_commit_store_commits_only_store_paths(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    (tmp_path / "staged.txt").write_text("s\n"); _git(tmp_path, "add", "staged.txt")
    (tmp_path / "docs" / "a.md").write_text("edited\n")
    _write(monkeypatch, "new-page.md")
    files = _git(tmp_path, "show", "--name-only", "--format=%s", "HEAD").split()
    assert files[:3] == ["iirc:", "write", "new-page.md"]
    assert sorted(files[3:]) == [".iirc/index.md", ".iirc/new-page.md"]
    status = _git(tmp_path, "status", "--porcelain")
    assert "A  staged.txt" in status and " M docs/a.md" in status


def test_commit_picks_up_an_earlier_uncommitted_page(tmp_path, monkeypatch):
    field = _project(tmp_path, monkeypatch)
    _page(field, "left-behind.md")
    _write(monkeypatch, "next.md")
    assert ".iirc/left-behind.md" in _git(tmp_path, "show", "--name-only", "--format=", "HEAD").split()


def test_commit_store_runs_only_without_an_operation_in_progress(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    head = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / ".git" / "MERGE_HEAD").write_text(head)
    _write(monkeypatch, "during-merge.md")
    assert (tmp_path / ".iirc" / "during-merge.md").is_file()
    assert _git(tmp_path, "rev-parse", "HEAD") == head
    assert "not committed: a merge or rebase is in progress" in capsys.readouterr().err


def test_commit_store_reports_a_failing_hook(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho refused by hook >&2\nexit 1\n"); hook.chmod(0o755)
    head = _git(tmp_path, "rev-parse", "HEAD")
    _write(monkeypatch, "hooked.md")                        # exits 0: no SystemExit
    assert (tmp_path / ".iirc" / "hooked.md").is_file() and _git(tmp_path, "rev-parse", "HEAD") == head
    assert "written, not committed: refused by hook" in capsys.readouterr().err


def test_verify_delete_index_commit(tmp_path, monkeypatch):
    field = _project(tmp_path, monkeypatch)
    _write(monkeypatch, "life.md")
    iirc.main(["verify", "life.md"])
    assert _git(tmp_path, "log", "-1", "--format=%s") == "iirc: verify life.md\n"
    iirc.main(["delete", "life.md"])
    assert _git(tmp_path, "log", "-1", "--format=%s") == "iirc: delete life.md\n"
    assert not (field / "life.md").exists() and "life.md" not in _git(tmp_path, "ls-files")
    (field / "index.md").write_text("intro\n")
    iirc.main(["index"])
    assert _git(tmp_path, "log", "-1", "--format=%s") == "iirc: index\n"


def test_store_lock_serializes_two_writers(tmp_path, monkeypatch, capsys):
    import threading
    field = _project(tmp_path, monkeypatch)
    store = iirc.project_store()
    _page(field, "one.md"); _page(field, "two.md")
    errors = []

    def commit(msg):
        try:
            iirc.save(store, msg)
        except Exception as e:   # pragma: no cover - surfaced by the assert
            errors.append(e)
    with iirc.store_lock(store.field):
        threads = [threading.Thread(target=commit, args=(f"iirc: write {n}",)) for n in ("one.md", "two.md")]
        for t in threads:
            t.start()
        import time; time.sleep(0.3)                          # both wait on the lock this test holds
        assert _git(tmp_path, "status", "--porcelain", "--", ".iirc").count("??") == 2
    for t in threads:
        t.join()
    assert not errors and "index.lock" not in capsys.readouterr().err
    assert _git(tmp_path, "status", "--porcelain", "--", ".iirc") == ""


def test_doctor_brief_counts_uncommitted(tmp_path, monkeypatch, capsys):
    field = _project(tmp_path, monkeypatch)
    iirc.write_config_file({"semantic": False})
    iirc.main(["doctor", "--brief"])
    assert "not committed" not in capsys.readouterr().out
    _page(field, "loose.md")
    iirc.main(["doctor", "--brief"])
    assert "1 store change not committed." in capsys.readouterr().out


def test_brief_does_not_warn_on_page_count(tmp_path, monkeypatch, capsys):
    field = _project(tmp_path, monkeypatch)
    iirc.write_config_file({"semantic": False})
    for i in range(51):
        _page(field, f"page-{i}.md")
    iirc.main(["doctor", "--brief"])
    out = capsys.readouterr().out
    assert out.startswith("iirc: 51 pages") and "is a lot" not in out


def _index(tmp_path, monkeypatch, vectors, root=None):
    """The vector store for the project store: one row per page, 768 float32 values each."""
    import numpy as np
    monkeypatch.setattr(iirc, "cache_dir", lambda: tmp_path / "cache")
    path = iirc.iirc_embed.store_path(tmp_path / "cache", iirc.field_name(root or tmp_path))
    rows = np.zeros((len(vectors), 768), dtype=np.float32)
    for i, head in enumerate(vectors.values()):
        rows[i, :len(head)] = head
    iirc.iirc_embed.save(path, iirc.iirc_embed.Vectors(list(vectors), [f"sha-{n}" for n in vectors], rows))
    return path


# a.md and b.md are 0.05 apart; far.md is at distance 1 from both
_CLOSE = {"a.md": (1.0, 0.0), "b.md": (0.95, 0.3122499), "far.md": (0.0, 0.0, 1.0)}


def test_near_duplicates_names_the_close_pair(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    _index(tmp_path, monkeypatch, _CLOSE)
    assert iirc.near_duplicates() == [(0.05, "a.md", "b.md")]


def test_a_link_across_kinds_keeps_a_pair_apart(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    _index(tmp_path, monkeypatch, _CLOSE)
    page = lambda kind, body: f"---\ntitle: t\nsummary: s\ntopics: [x]\nkind: {kind}\n---\n{body}\n"
    (tmp_path / ".iirc" / "a.md").write_text(page("decision", "When. See [[b]]."))
    (tmp_path / ".iirc" / "b.md").write_text(page("procedure", "How."))
    assert iirc.flagged_pairs() == []
    (tmp_path / ".iirc" / "b.md").write_text(page("decision", "Also when."))   # same kind: a link is not enough
    assert iirc.flagged_pairs() == [(0.05, "a.md", "b.md")]
    (tmp_path / ".iirc" / "a.md").write_text(page("decision", "When."))
    (tmp_path / ".iirc" / "b.md").write_text(page("procedure", "How."))        # different kinds, no link
    assert iirc.flagged_pairs() == [(0.05, "a.md", "b.md")]


def test_near_duplicates_without_an_index_is_empty(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    monkeypatch.setattr(iirc, "cache_dir", lambda: tmp_path / "cache")
    assert iirc.near_duplicates() == []                      # no index file
    path = _index(tmp_path, monkeypatch, _CLOSE)
    import numpy as np
    np.savez(path, names=np.asarray(["a.md"]), vecs=np.zeros((1, 768), dtype=np.float32))
    assert iirc.near_duplicates() == []                      # a file this version did not write


def test_near_duplicates_reuses_the_cached_result(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    _index(tmp_path, monkeypatch, _CLOSE)
    first = iirc.near_duplicates()
    calls = []
    real = iirc.page_vectors
    monkeypatch.setattr(iirc, "page_vectors", lambda: calls.append(1) or real())
    assert iirc.near_duplicates() == first and calls == []
    other = tmp_path / "other"; (other / ".iirc").mkdir(parents=True)
    _index(tmp_path, monkeypatch, {"c.md": (1.0, 0.0), "d.md": (0.96, 0.28)}, root=other)
    iirc.set_root(other)
    assert iirc.near_duplicates() == [(0.04, "c.md", "d.md")] and calls == [1]
    iirc.set_root(tmp_path)
    assert {str(tmp_path), str(other)} <= set(iirc.read_state_json("pairs.json"))   # one root's write keeps the other's entry
    assert iirc.near_duplicates() == first and calls == [1]


def test_near_duplicates_survives_a_bad_cache_and_a_short_read(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    iirc.write_config_file({"semantic": True})
    _index(tmp_path, monkeypatch, _CLOSE)
    first = iirc.near_duplicates()
    state = iirc.read_state_json("pairs.json")
    state[str(tmp_path)]["pairs"] = [[0.05, "a.md"]]            # a shape this version never wrote
    iirc.write_state_json("pairs.json", state)
    assert iirc.near_duplicates() == first
    state[str(tmp_path)]["pairs"] = [["x", "a.md", "b.md"]]     # a distance doctor could not print
    iirc.write_state_json("pairs.json", state)
    assert iirc.near_duplicates() == first
    iirc.write_state_json("pairs.json", {})
    real = iirc.page_vectors
    monkeypatch.setattr(iirc, "page_vectors", lambda: {})     # the index was locked between the two reads
    assert iirc.near_duplicates() == []
    monkeypatch.setattr(iirc, "page_vectors", real)
    assert iirc.near_duplicates() == first                    # the short result was not kept
    iirc.write_state_json("pairs.json", {})
    assert iirc.near_duplicates(budget=0) == [] and iirc.read_state_json("pairs.json") == {}
    monkeypatch.setattr(iirc, "near_duplicates", lambda budget=None: 1 / 0)
    iirc.main(["doctor", "--brief"])                          # a hook never fails on this signal
    assert capsys.readouterr().out.startswith("iirc: 0 pages")


def test_doctor_names_near_duplicate_pairs(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    iirc.write_config_file({"semantic": True})
    _index(tmp_path, monkeypatch, _CLOSE)
    with pytest.raises(SystemExit):
        iirc.main(["doctor"])
    assert "note near-duplicate pages (distance 0.050): a.md | b.md" in capsys.readouterr().out


def test_brief_counts_near_duplicate_pairs(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    iirc.write_config_file({"semantic": True})
    iirc.main(["doctor", "--brief"])
    assert "near-duplicate" not in capsys.readouterr().out
    _index(tmp_path, monkeypatch, _CLOSE)
    iirc.main(["doctor", "--brief"])
    assert "1 near-duplicate pair: iirc doctor names them; merge each, or link one page to the other with [[name]] if their kinds differ." in capsys.readouterr().out
    iirc.write_config_file({"semantic": False})               # string mode: nothing refreshes the index
    iirc.main(["doctor", "--brief"])
    assert "near-duplicate" not in capsys.readouterr().out


def test_brief_reports_a_slow_scan(tmp_path, monkeypatch, capsys):
    field = _project(tmp_path, monkeypatch)
    iirc.write_config_file({"semantic": False})
    _page(field, "one.md")
    iirc.main(["doctor", "--brief"])
    assert "start scan" not in capsys.readouterr().out
    monkeypatch.setattr(iirc, "SCAN_BUDGET", 0)
    iirc.main(["doctor", "--brief"])
    out = capsys.readouterr().out
    assert "The start scan took" in out and "over 0 cited files, past the 0 s budget; tell the creator." in out


# --- remote stores ------------------------------------------------------------


def _remote(tmp_path, monkeypatch, write="agent"):
    """A project repository with a project store and a remote store cloned from a bare repository."""
    proj = tmp_path / "proj"; proj.mkdir()
    _project(proj, monkeypatch)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    bare = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    (proj / ".claude").mkdir()
    (proj / ".claude" / "iirc.toml").write_text(
        f'write = "{write}"\n\n[stores.project]\nkind = "project"\npath = ".iirc"\n\n[stores.agent]\nkind = "remote"\nurl = "{bare}"\n')
    iirc.set_root(proj)
    agent = iirc.store_named("agent")
    assert iirc.clone_store(agent) is None
    monkeypatch.setattr(iirc, "tool", _fake_tool(proj / ".iirc"))
    return proj, agent, bare


def _other_clone(tmp_path, bare, name="other"):
    other = tmp_path / name
    _git(tmp_path, "clone", "-q", str(bare), str(other))
    return other


def _push_page(other, page, text="from the other instance\n"):
    (other / page).write_text(f"---\ntitle: O\nsummary: o\ntopics: [t]\nkind: finding\n---\n{text}")
    _git(other, "add", page); _git(other, "commit", "-qm", f"other {page}"); _git(other, "push", "-q", "origin", "main")


def test_stores_add_writes_config_and_clones(tmp_path, monkeypatch):
    proj = tmp_path / "proj"; proj.mkdir()
    _project(proj, monkeypatch)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    bare = tmp_path / "remote.git"; _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    iirc.main(["stores", "add", "agent", str(bare), "--default"])
    text = (proj / ".claude" / "iirc.toml").read_text()
    assert 'write = "agent"' in text and "[stores.project]" in text and f'url = "{bare}"' in text
    agent = iirc.store_named("agent")
    assert (agent.dir / "index.md").is_file()
    assert _git(bare, "log", "-1", "--format=%s", "main") == "iirc: create store agent\n"
    assert _git(proj, "show", "--name-only", "--format=%s", "HEAD").split() == ["iirc:", "add", "store", "agent", ".claude/iirc.toml"]


def test_push_store_rebases_once(tmp_path, monkeypatch, capsys):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    _push_page(_other_clone(tmp_path, bare), "theirs.md")
    _write(monkeypatch, "mine.md")
    assert "not pushed" not in capsys.readouterr().err
    tree = _git(bare, "ls-tree", "--name-only", "main").split()
    assert "theirs.md" in tree and "mine.md" in tree
    assert "IIRC-Project: " in _git(bare, "log", "-1", "--format=%B", "main")


def test_push_store_conflict_keeps_the_commit(tmp_path, monkeypatch, capsys):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    _write(monkeypatch, "shared.md")
    _push_page(_other_clone(tmp_path, bare), "shared.md", "their version\n")
    _write(monkeypatch, "shared.md", "--summary", "mine changed")
    err = capsys.readouterr().err
    assert "not pushed" in err and "iirc sync" in err
    assert not iirc.rebase_in_progress(agent.repo)
    assert _git(agent.repo, "log", "-1", "--format=%s") == "iirc: write shared.md\n"
    assert iirc.unpushed(agent) == 1


def test_sync_commits_pulls_and_pushes(tmp_path, monkeypatch, capsys):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    monkeypatch.setattr(iirc, "reindex", lambda **k: None)
    _page(agent.dir, "loose.md")
    _push_page(_other_clone(tmp_path, bare), "theirs.md")
    iirc.main(["sync"])
    out = capsys.readouterr().out
    assert out.startswith("agent: committed 1 file, pulled 1 file, pushed")
    tree = _git(bare, "ls-tree", "--name-only", "main").split()
    assert "loose.md" in tree and "theirs.md" in tree and iirc.unpushed(agent) == 0


def test_project_store_never_pushes(tmp_path, monkeypatch):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    project_remote = tmp_path / "project.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(project_remote))
    _git(proj, "remote", "add", "origin", str(project_remote))
    _write(monkeypatch, "local.md", "--store", "project")
    assert _git(proj, "log", "-1", "--format=%s") == "iirc: write local.md\n"
    assert _git(project_remote, "rev-list", "--all") == ""          # nothing was pushed


def test_brief_pulls_only_at_session_start(tmp_path, monkeypatch, capsys):
    import io
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    iirc.write_config_file({"semantic": False})
    started = []
    monkeypatch.setattr(iirc, "start_background", lambda argv: started.append(argv))
    _push_page(_other_clone(tmp_path, bare), "theirs.md")
    head = _git(agent.repo, "rev-parse", "HEAD")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SubagentStart"})))
    iirc.main(["doctor", "--brief", "--hook"]); capsys.readouterr()
    assert _git(agent.repo, "rev-parse", "HEAD") == head and not started
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart", "source": "startup"})))
    iirc.main(["doctor", "--brief", "--hook"])
    assert (agent.dir / "theirs.md").is_file() and "Pulled 1 page" in capsys.readouterr().out
    assert started and started[0][-1] == "index"


def test_doctor_brief_counts_unpushed(tmp_path, monkeypatch, capsys):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    iirc.write_config_file({"semantic": False})
    iirc.main(["doctor", "--brief"])
    assert "not pushed" not in capsys.readouterr().out
    _page(agent.dir, "local-only.md"); _git(agent.repo, "add", "."); _git(agent.repo, "commit", "-qm", "local")
    iirc.main(["doctor", "--brief"])
    assert "1 store commit not pushed (iirc sync)." in capsys.readouterr().out


def test_project_id_normalizes_origin(tmp_path):
    same = ["git@github.com:DaftDoki/agent-builder.git", "https://github.com/daftdoki/agent-builder",
            "ssh://git@github.com:22/daftdoki/agent-builder.git", "https://user@github.com/DaftDoki/agent-builder.git/"]
    assert {iirc.normalize_origin(u) for u in same} == {"github.com/daftdoki/agent-builder"}
    plain = tmp_path / "My_Project"; plain.mkdir()
    assert iirc.project_id(plain) == "my-project"


def test_remote_page_gets_project_and_prefixed_refs(tmp_path, monkeypatch):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    _write(monkeypatch, "cites.md", "--ref", "docs/a.md")
    fm = iirc.page_frontmatter("cites.md", agent)
    pid = iirc.project_id()
    sha = _git(proj, "log", "-1", "--format=%h", "--", "docs/a.md").strip()
    assert fm["project"] == pid and fm["refs"] == [f"{pid}:docs/a.md@{sha}"]
    assert iirc.suspicion(fm) == []


def test_ref_in_another_project_gives_no_signal(tmp_path, monkeypatch, capsys):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    marker = tmp_path / "ran"
    _page(agent.dir, "theirs.md", extra=f"project: github.com/x/other\nrefs:\n- github.com/x/other:docs/a.md@deadbee\ncheck: touch {marker}\n")
    fm = iirc.page_frontmatter("theirs.md", agent)
    assert iirc.suspicion(fm, run_checks=True) == []
    iirc.main(["doubt"])
    assert "not checked here" in capsys.readouterr().err and not marker.exists()
    iirc.main(["verify", "agent/theirs.md"])
    assert "verified agent/theirs.md" in capsys.readouterr().out and not marker.exists()
    assert iirc.page_frontmatter("theirs.md", agent)["refs"] == ["github.com/x/other:docs/a.md@deadbee"]


def test_verify_keeps_other_project_refs(tmp_path, monkeypatch):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    pid = iirc.project_id()
    old = _git(proj, "log", "-1", "--format=%h").strip()
    (proj / "docs" / "a.md").write_text("changed\n"); _git(proj, "commit", "-qam", "change")
    new = _git(proj, "log", "-1", "--format=%h").strip()
    _page(agent.dir, "mixed.md", extra=f"project: {pid}\nrefs:\n- {pid}:docs/a.md@{old}\n- github.com/x/other:lib/b.py@abc1234\n")
    iirc.main(["verify", "mixed.md"])
    assert iirc.page_frontmatter("mixed.md", agent)["refs"] == [f"{pid}:docs/a.md@{new}", "github.com/x/other:lib/b.py@abc1234"]


def test_search_ranks_current_project_first(tmp_path, monkeypatch, capsys):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    iirc.write_config_file({"semantic": False})
    pid = iirc.project_id()
    _page(agent.dir, "aaa-elsewhere.md", "zeppelin notes", extra="project: github.com/x/other\n")
    _page(agent.dir, "zzz-here.md", "zeppelin notes", extra=f"project: {pid}\n")
    iirc.main(["search", "zeppelin"])
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in lines] == ["agent/zzz-here.md", "agent/aaa-elsewhere.md"]


def test_doctor_warns_about_non_page_md(tmp_path, monkeypatch):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    (agent.dir / "README.md").write_text("# iirc repo\n")
    assert iirc.non_pages(agent) == ["README.md"]


def test_guard_denies_a_raw_read_in_a_remote_store():
    import subprocess
    shim = ROOT / "scripts" / "guard.sh"
    def run(payload):
        return subprocess.run(["sh", str(shim)], input=json.dumps(payload), capture_output=True, text=True).stdout
    page = "/home/u/.local/share/dokidlc-iirc/stores/agent-3f9c2a10/a-page.md"
    for payload in ({"tool_name": "Bash", "tool_input": {"command": f"cat {page}"}}, {"tool_name": "Read", "tool_input": {"file_path": page}}):
        out = json.loads(run(payload))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "iirc read STORE/a-page.md" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert run({"tool_name": "Read", "tool_input": {"file_path": page.replace("a-page.md", "index.md")}}) == ""


def test_load_stores_rejects_two_project_stores(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "iirc.toml").write_text('[stores.project]\nkind = "project"\n[stores.second]\nkind = "project"\npath = "m2"\n')
    with pytest.raises(iirc.ConfigError) as e:
        iirc.load_stores(tmp_path)
    assert "at most one project store" in str(e.value)


def test_brief_starts_a_background_index_after_a_pull(tmp_path, monkeypatch, capsys):
    """The hook returns within its budget, and the reindex runs detached in its own session."""
    import io, os, time
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    iirc.write_config_file({"semantic": False})
    procs = []
    real = iirc.start_background
    asked = []
    monkeypatch.setattr(iirc, "start_background", lambda argv: asked.append(argv) or procs.append(real(["sleep", "3"])))
    _push_page(_other_clone(tmp_path, bare), "theirs.md")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart", "source": "startup"})))
    t0 = time.monotonic()
    iirc.main(["doctor", "--brief", "--hook"])
    assert time.monotonic() - t0 < iirc.BRIEF_PULL_BUDGET + 2      # did not wait for the 3 s child
    p = procs[0]
    try:
        assert p.poll() is None and os.getsid(p.pid) != os.getsid(0)   # still running, in its own session
    finally:
        p.kill()
    assert "Pulled 1 page" in capsys.readouterr().out and asked[0][-1] == "index"


def test_brief_names_doctor_fix_when_only_a_remote_store_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st")); monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    iirc.write_config_file({"semantic": False})
    (tmp_path / ".claude").mkdir(); (tmp_path / ".claude" / "iirc.toml").write_text('[stores.agent]\nkind = "remote"\nurl = "u"\n')
    iirc.main(["doctor", "--brief"])
    assert "iirc doctor --fix" in capsys.readouterr().out


def test_last_line_prefers_git_fatal_line():
    import subprocess
    p = subprocess.CompletedProcess([], 128, "", "fatal: '/x/remote.git' does not appear to be a git repository\nfatal: Could not read from remote repository.\n\nPlease make sure you have the correct access rights\nand the repository exists.\n")
    assert iirc.last_line(p) == "fatal: '/x/remote.git' does not appear to be a git repository"
    assert iirc.last_line(subprocess.CompletedProcess([], 1, "", "")) == "git exited 1"


# --- refs fire on cited content ------------------------------------------------


def _cited(tmp_path, monkeypatch, body="intro\n\n## Alpha\n\nalpha text\n\n## Beta\n\nbeta text\n"):
    """A project with docs/doc.md committed; returns its short sha."""
    _project(tmp_path, monkeypatch)
    (tmp_path / "docs" / "doc.md").write_text(body)
    _git(tmp_path, "add", "docs/doc.md"); _git(tmp_path, "commit", "-qm", "doc")
    return _git(tmp_path, "log", "-1", "--format=%h").strip()


def test_ref_follows_a_rename(tmp_path, monkeypatch, capsys):
    sha = _cited(tmp_path, monkeypatch)
    _page(tmp_path / ".iirc", "cites.md", extra=f"refs:\n- docs/doc.md@{sha}\n")
    _git(tmp_path, "mv", "docs/doc.md", "docs/moved.md"); _git(tmp_path, "commit", "-qm", "move")
    fm = iirc.page_frontmatter("cites.md")
    assert iirc.suspicion(fm) == []
    iirc.main(["verify", "cites.md"])
    assert iirc.page_frontmatter("cites.md")["refs"][0].startswith("docs/moved.md@")


def test_ref_changed_then_reverted_is_clean(tmp_path, monkeypatch):
    sha = _cited(tmp_path, monkeypatch)
    doc = tmp_path / "docs" / "doc.md"
    original = doc.read_text()
    doc.write_text(original + "edit\n"); _git(tmp_path, "commit", "-qam", "edit")
    assert iirc.ref_changed(f"docs/doc.md@{sha}", tmp_path)
    doc.write_text(original); _git(tmp_path, "commit", "-qam", "revert")
    assert iirc.ref_changed(f"docs/doc.md@{sha}", tmp_path) is None


SECTIONED = "intro\n\n## Alpha\n\nalpha text\n\n```\n## Gamma in a fence\n```\n\nalpha after the fence\n\n## Beta\n\nbeta text\n"


def test_section_ref_ignores_edits_elsewhere(tmp_path, monkeypatch):
    sha = _cited(tmp_path, monkeypatch, SECTIONED)
    doc = tmp_path / "docs" / "doc.md"
    doc.write_text(SECTIONED.replace("beta text", "beta rewritten")); _git(tmp_path, "commit", "-qam", "beta")
    assert iirc.ref_changed(f"docs/doc.md#Alpha@{sha}", tmp_path) is None
    assert iirc.ref_changed(f"docs/doc.md@{sha}", tmp_path)          # the whole file did change


def test_section_ref_fires_on_its_own_text(tmp_path, monkeypatch):
    sha = _cited(tmp_path, monkeypatch, SECTIONED)
    doc = tmp_path / "docs" / "doc.md"
    doc.write_text(SECTIONED.replace("alpha after the fence", "alpha changed after the fence")); _git(tmp_path, "commit", "-qam", "alpha")
    reason = iirc.ref_changed(f"docs/doc.md#Alpha@{sha}", tmp_path)
    assert reason and "docs/doc.md#Alpha changed since cited" in reason


def test_section_ref_missing_heading_is_suspect(tmp_path, monkeypatch):
    sha = _cited(tmp_path, monkeypatch, SECTIONED)
    doc = tmp_path / "docs" / "doc.md"
    doc.write_text(SECTIONED.replace("## Beta", "## Renamed")); _git(tmp_path, "commit", "-qam", "rename heading")
    assert "section no longer exists" in iirc.ref_changed(f"docs/doc.md#Beta@{sha}", tmp_path)


def test_section_ref_heading_with_a_colon(tmp_path, monkeypatch):
    body = "## Review record: plan\n\nfirst\n\n## Other\n\nx\n"
    sha = _cited(tmp_path, monkeypatch, body)
    _page(tmp_path / ".iirc", "colon.md", extra=f"refs:\n- 'docs/doc.md#Review record: plan@{sha}'\n")
    (tmp_path / "docs" / "doc.md").write_text(body.replace("first", "second")); _git(tmp_path, "commit", "-qam", "edit")
    signals = iirc.suspicion(iirc.page_frontmatter("colon.md"))
    assert [s for s, _ in signals] == ["ref"] and "Review record: plan" in signals[0][1]


def test_verify_moves_a_section_ref(tmp_path, monkeypatch):
    sha = _cited(tmp_path, monkeypatch, SECTIONED)
    _page(tmp_path / ".iirc", "sect.md", extra=f"refs:\n- docs/doc.md#Alpha@{sha}\n")
    _git(tmp_path, "mv", "docs/doc.md", "docs/moved.md"); _git(tmp_path, "commit", "-qm", "move")
    assert iirc.suspicion(iirc.page_frontmatter("sect.md")) == []
    iirc.main(["verify", "sect.md"])
    ref = iirc.page_frontmatter("sect.md")["refs"][0]
    assert ref.startswith("docs/moved.md#Alpha@") and not ref.endswith(sha)


def test_write_section_ref_fills_and_refuses_a_missing_heading(tmp_path, monkeypatch, capsys):
    sha = _cited(tmp_path, monkeypatch, SECTIONED)
    _write(monkeypatch, "with-section.md", "--ref", "docs/doc.md#Beta")
    assert iirc.page_frontmatter("with-section.md")["refs"] == [f"docs/doc.md#Beta@{sha}"]
    with pytest.raises(SystemExit):
        _write(monkeypatch, "bad-section.md", "--ref", "docs/doc.md#Nope")
    assert "no heading 'Nope'" in capsys.readouterr().err


def test_whole_file_ref_needs_a_hex_sha(tmp_path, monkeypatch):
    _cited(tmp_path, monkeypatch)
    for bad in ("docs/doc.md@HEAD", "docs/doc.md@HEAD~1", "docs/doc.md@zzzzzzz"):
        assert "cited sha is not hex" in iirc.ref_changed(bad, tmp_path), bad


def test_names_are_iirc(tmp_path, monkeypatch):
    assert iirc.STORE_CONFIG == ".claude/iirc.toml"
    assert iirc.CLAUDE_MD_MARK == "<!-- iirc -->"
    stores, _ = iirc.load_stores(tmp_path)
    assert stores[0].dir == tmp_path / ".iirc"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c")); monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "d")); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "s"))
    assert [iirc.config_file().parent.name, iirc.data_dir().name, iirc.state_dir().name] == ["dokidlc-iirc"] * 3


MIGRATION_LINE = "iirc: this repository or machine still uses the memory plugin's layout."


def _old_layout(root):
    """A repository as the memory plugin left it: store, config, CLAUDE.md section, and settings."""
    (root / ".memory").mkdir()
    (root / ".memory" / "index.md").write_text("---\ntitle: Memory\n---\n\n<!-- memory format 1, written by memory abc1234 on 2026-10-01 -->\n")
    (root / ".memory" / "a-page.md").write_text("---\ntitle: A\nsummary: a\n---\nRun `memory read b.md` and `memory doctor --fix`; memory as a word stays.\n")
    (root / ".claude").mkdir()
    (root / ".claude" / "memory.toml").write_text('ui = true\n\n[stores.project]\nkind = "project"\npath = ".memory"\n')
    (root / ".claude" / "settings.json").write_text(json.dumps({"enabledPlugins": {"memory@dokidlc": True, "questlog@dokidlc": True}}, indent=2) + "\n")
    (root / "CLAUDE.md").write_text("# Project\n\n## Memory <!-- memory -->\n\n`.memory/` holds what past sessions learned.\n\n## Other\n\nKept.\n")


def _brief(argv, monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart", "session_id": "m"})))
    iirc.main(argv)
    return capsys.readouterr().out


def test_doctor_brief_offers_migration(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    repo = tmp_path / "repo"; repo.mkdir(); _old_layout(repo)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    for argv in (["doctor", "--brief"], ["doctor", "--brief", "--hook"]):
        assert MIGRATION_LINE in _brief(argv, monkeypatch, capsys)
    machine = tmp_path / "machine"; machine.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(machine))
    (Path(iirc.os.environ["XDG_DATA_HOME"]) / "dokidlc-memory").mkdir(parents=True)
    for argv in (["doctor", "--brief"], ["doctor", "--brief", "--hook"]):
        assert MIGRATION_LINE in _brief(argv, monkeypatch, capsys)


def test_migrate_fixture(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    repo = tmp_path / "repo"; repo.mkdir(); _repo(repo); _old_layout(repo)
    (repo / ".claude" / "settings.local.json").write_text(json.dumps({"enabledPlugins": {"memory@memory-dev": True}}) + "\n")
    _git(repo, "add", "."); _git(repo, "commit", "-qm", "old layout")
    bases = [Path(iirc.os.environ[v]) for v in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME")]
    for b in bases:
        (b / "dokidlc-memory").mkdir(parents=True); (b / "dokidlc-memory" / "kept.txt").write_text("x\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    reindexed = []
    monkeypatch.setattr(iirc, "reindex", lambda **k: reindexed.append(1))
    commits = _git(repo, "rev-list", "--count", "HEAD")
    assert MIGRATION_LINE in _brief(["doctor", "--brief"], monkeypatch, capsys)

    iirc.main(["migrate"])
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1] == 'Suggested commit: git commit -m "iirc: migrate from the memory plugin"'
    assert any("settings.local.json" in line and "memory@memory-dev" in line for line in out)
    assert not (repo / ".memory").exists() and sorted(p.name for p in (repo / ".iirc").iterdir()) == ["a-page.md", "index.md"]
    assert not (repo / ".claude" / "memory.toml").exists()
    assert 'path = ".iirc"' in (repo / ".claude" / "iirc.toml").read_text()
    claude_md = (repo / "CLAUDE.md").read_text()
    assert "## IIRC <!-- iirc -->" in claude_md and "<!-- memory -->" not in claude_md and "## Other\n\nKept." in claude_md
    settings = json.loads((repo / ".claude" / "settings.json").read_text())["enabledPlugins"]
    assert settings == {"iirc@dokidlc": True, "questlog@dokidlc": True}
    assert "memory@memory-dev" in (repo / ".claude" / "settings.local.json").read_text()
    page = (repo / ".iirc" / "a-page.md").read_text()
    assert "`iirc read b.md`" in page and "`iirc doctor --fix`" in page and "memory as a word stays" in page
    assert "iirc format" in (repo / ".iirc" / "index.md").read_text() and reindexed
    for b in bases:
        assert not (b / "dokidlc-memory").exists() and (b / "dokidlc-iirc" / "kept.txt").is_file()
    assert _git(repo, "rev-list", "--count", "HEAD") == commits
    assert ".iirc/a-page.md" in _git(repo, "diff", "--cached", "--name-only")

    iirc.main(["migrate"])
    assert capsys.readouterr().out.strip() == "nothing to migrate"
    assert MIGRATION_LINE not in _brief(["doctor", "--brief"], monkeypatch, capsys)


def test_docs_name_iirc():
    """The skill and the docs a reader acts on name iirc; only lines about the migration keep the old names."""
    docs = [ROOT / "skills" / "iirc" / "SKILL.md", *sorted((ROOT / "skills" / "iirc" / "references").glob("*.md")),
            ROOT / "README.md", ROOT / "INSTALL.md", ROOT / "DEVELOPMENT.md"]
    old = re.compile(r"`memory [a-z]|\.memory/|memory\.toml|bin/memory|memory@")
    hits = [f"{d.relative_to(ROOT)}:{n}" for d in docs if d.is_file() for n, line in enumerate(d.read_text().splitlines(), 1)
            if old.search(line) and "migrat" not in line]
    assert (ROOT / "skills" / "iirc" / "SKILL.md").is_file() and hits == []


def test_migrate_never_stages_machine_dirs(tmp_path, monkeypatch, capsys):
    """When the machine directories sit inside the repository (a home directory under git), they move but are never staged."""
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    repo = tmp_path / "home"; repo.mkdir(); _repo(repo); _old_layout(repo)
    _git(repo, "add", "."); _git(repo, "commit", "-qm", "old layout")
    for var, sub in (("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", ".local/share"), ("XDG_STATE_HOME", ".local/state")):
        monkeypatch.setenv(var, str(repo / sub)); (repo / sub / "dokidlc-memory").mkdir(parents=True); (repo / sub / "dokidlc-memory" / "f.txt").write_text("x\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    monkeypatch.setattr(iirc, "reindex", lambda **k: None)
    iirc.main(["migrate"]); capsys.readouterr()
    assert (repo / ".local" / "share" / "dokidlc-iirc").is_dir()
    assert "dokidlc" not in _git(repo, "diff", "--cached", "--name-only")


def test_recall_verdicts_say_why_each_candidate_was_left_out(monkeypatch):
    monkeypatch.setattr(iirc, "max_suggested", lambda: 1)
    rows = [
        {"filename": "a.md", "via": ["semantic"], "distance": 0.2},
        {"filename": "b.md", "via": ["semantic"], "distance": 0.25},
        {"filename": "c.md", "via": ["semantic"], "distance": 0.31},
        {"filename": "d.md", "via": ["semantic"], "distance": 0.5},
        {"filename": "e.md", "via": ["plain"], "rare_terms": ["plain"]},
        {"filename": "f.md", "via": ["word"], "rare_terms": []},
    ]
    v = iirc.recall_verdicts(rows)
    assert [r["verdict"] for r in v] == ["passed", "over_max", "needs_term", "too_far", "plain_word", "common_term"]
    assert [r["rank"] for r in v] == [0, 1, 2, 3, 4, 5]
    assert [r["filename"] for r in iirc.recall_filter(rows)] == ["a.md"]


def test_recall_knobs_come_from_iirc_toml(tmp_path):
    (tmp_path / ".claude").mkdir()
    toml = tmp_path / ".claude" / "iirc.toml"
    toml.write_text("[recall.nomic-embed-text]\nsemantic_only = 0.3\n")
    iirc.set_root(tmp_path)
    assert iirc.RECALL == {"semantic_only": 0.3, "both": 0.38} and iirc.CONFIG_ERROR is None
    near = [{"filename": "a.md", "via": ["semantic"], "distance": 0.29}]
    assert [r["rule"] for r in iirc.recall_filter(near)] == ["meaning"]
    for bad, says in (("semantic_only = 0.9", "from 0.1 to 0.6"), ("semantic_only = 0.4", "at least semantic_only"), ("loose = 0.3", "no knob 'loose'")):
        toml.write_text(f"[recall.nomic-embed-text]\n{bad}\n")
        iirc.set_root(tmp_path)
        assert says in iirc.CONFIG_ERROR and iirc.RECALL == {"semantic_only": 0.28, "both": 0.38}
    toml.unlink(); iirc.set_root(tmp_path)


def test_rotate_logs_moves_last_month_aside_and_reads_both(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st")); monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s")
    d = tmp_path / "st" / "dokidlc-iirc"; d.mkdir(parents=True)
    (d / "log.jsonl").write_text(json.dumps({"ts": "2020-01-31T23:00:00Z", "session": "s", "cmd": "read", "pages": ["a.md"]}) + "\n")
    iirc.rotate_logs()
    assert (d / "log-2020-01.jsonl").is_file() and not (d / "log.jsonl").exists()
    iirc.log_event("read", pages=["b.md"])
    assert [r["pages"] for r in iirc.read_log(session="s")] == [["a.md"], ["b.md"]]
    # past RETAIN_DAYS by its last write, a rotated file goes
    old = time.time() - (iirc.RETAIN_DAYS + 1) * 86400
    os.utime(d / "log-2020-01.jsonl", (old, old))
    iirc.rotate_logs()
    assert not (d / "log-2020-01.jsonl").exists() and (d / "log.jsonl").is_file()


def test_a_page_the_line_had_no_room_for_is_logged_line_cut(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s10"); iirc.set_root(tmp_path)
    rows = [{"filename": f"{c}.md", "via": ["semantic"], "distance": 0.1, "summary": "x" * 80, "fm": {}} for c in "abc"]
    monkeypatch.setattr(iirc, "hybrid_search", lambda q: rows)
    monkeypatch.setattr(iirc, "recall_max_bytes", lambda: 10)   # room for the first page only
    line = iirc.run_recall("a query long enough to search", "prompt", {})
    assert line.count("`iirc read ") == 1
    evals = [json.loads(x) for f in (tmp_path / "st" / "dokidlc-iirc").glob("eval-*.jsonl") for x in f.read_text().splitlines()]
    assert [e["verdict"] for e in evals] == ["passed", "line_cut", "line_cut"]
    assert iirc.read_log(session="s10")[-1]["pages"] == ["a.md"]


# --- tune --------------------------------------------------------------------


def _jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def _tune_fixture(tmp_path, monkeypatch):
    """Two sessions: s1 with recall ids, a prompts file, eval rows, and a transcript; s0 from before recall ids, joined by time."""
    repo = tmp_path / "repo"; repo.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude")); monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "tuner")
    iirc.set_root(repo)
    st = tmp_path / "st" / "dokidlc-iirc"
    tx_dir = tmp_path / "claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(repo.resolve()))
    first = "why does the build fail on this machine after the upgrade"
    r = str(repo.resolve())
    _jsonl(st / "log.jsonl", [
        {"ts": "2026-10-01T09:00:00Z", "session": "s0", "repo": r, "cmd": "start", "knobs": {"semantic_only": 0.28, "both": 0.34}, "page_count": 5},
        {"ts": "2026-10-01T09:00:05Z", "session": "s0", "repo": r, "cmd": "recall", "hits": 1, "pages": ["a.md"], "scores": ["70% match, meaning"], "via": "prompt", "chars": 50},
        {"ts": "2026-10-08T10:00:00Z", "session": "s1", "repo": r, "cmd": "start", "knobs": {"semantic_only": 0.28, "both": 0.34}, "page_count": 5},
        {"ts": "2026-10-08T10:00:05Z", "session": "s1", "repo": r, "cmd": "recall", "hits": 2, "pages": ["a.md", "b.md"],
         "scores": ["75% match, meaning", "70% match, meaning+term"], "via": "prompt", "recall_id": "r1", "prompt_hash": iirc.prompt_hash(first)},
        {"ts": "2026-10-08T10:00:20Z", "session": "s1", "repo": r, "cmd": "search", "query": "build failure", "hits": 1, "pages": ["c.md"]},
        {"ts": "2026-10-08T10:00:30Z", "session": "s1", "repo": r, "cmd": "read", "pages": ["project/a.md", "c.md"]},
        {"ts": "2026-10-08T10:01:00Z", "session": "s1", "repo": r, "cmd": "skipped", "reason": "short"},
        {"ts": "2026-10-08T10:02:00Z", "session": "s1", "repo": r, "cmd": "recall", "hits": 0, "pages": [], "via": "failure", "recall_id": "r2", "tool_use_id": "tu2"},
        {"ts": "2026-10-08T10:03:00Z", "session": "s1", "repo": r, "cmd": "read", "pages": ["b.md"]},
        {"ts": "2026-10-08T10:02:31Z", "session": "s1", "repo": r, "cmd": "recall", "hits": 0, "pages": [], "via": "failure", "recall_id": "r3", "tool_use_id": "tu3"},
        {"ts": "2026-10-08T10:00:00Z", "session": "elsewhere", "repo": "/other", "cmd": "recall", "pages": ["a.md"], "via": "prompt"},
    ])
    _jsonl(st / "prompts" / "s1.jsonl", [{"ts": "2026-10-08T10:00:05Z", "prompt_hash": iirc.prompt_hash(first), "excerpt": first, "recall_id": "r1"}])
    cand = {"ts": "2026-10-08T10:00:05Z", "session": "s1", "repo": r, "cmd": "candidate", "recall_id": "r1", "via": "prompt", "store": "project", "kind": "finding"}
    _jsonl(st / "eval-2026-10.jsonl", [
        {**cand, "rank": 0, "page": "a.md", "distance": 0.25, "paths": ["semantic"], "rare_terms": [], "head_terms": [], "rule": "meaning", "verdict": "passed"},
        {**cand, "rank": 1, "page": "b.md", "distance": 0.30, "paths": ["semantic", "v1.2"], "rare_terms": ["v1.2"], "head_terms": [], "rule": "meaning+term", "verdict": "passed"},
        {**cand, "rank": 2, "page": "c.md", "distance": 0.36, "paths": ["semantic"], "rare_terms": [], "head_terms": [], "rule": None, "verdict": "too_far"},
        {**cand, "rank": 3, "page": "d.md", "distance": 0.45, "paths": ["semantic"], "rare_terms": [], "head_terms": [], "rule": None, "verdict": "too_far"},
        *({**cand, "rank": 4 + n, "page": f"near-{n}.md", "distance": dist, "paths": ["semantic"], "rare_terms": [], "head_terms": [], "rule": None,
           "verdict": "too_far"} for n, dist in enumerate((0.365, 0.355, 0.37))),
    ])

    def user(ts, content, **kw):
        return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": content}, **kw}

    def tool(ts, tid, command, **kw):
        return {"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": command}}]}, **kw}
    _jsonl(tx_dir / "s1.jsonl", [
        user("2026-10-08T10:00:04.500Z", first),
        tool("2026-10-08T10:00:08.000Z", "tu0", "git status", isSidechain=True),   # a subagent's call is not the main thread's
        tool("2026-10-08T10:00:10.000Z", "tu1", "iirc read a.md"),
        user("2026-10-08T10:00:11.000Z", [{"type": "tool_result", "tool_use_id": "tu1", "content": "page"}]),
        user("2026-10-08T10:00:59.900Z", "ok"),
        tool("2026-10-08T10:01:50.000Z", "tu2", "make build"),
        user("2026-10-08T10:01:51.000Z", [{"type": "tool_result", "tool_use_id": "tu2", "content": "Exit code 2\nboom: no rule"}]),
    ])
    _jsonl(tx_dir / "s1" / "subagents" / "agent-x.jsonl", [
        tool("2026-10-08T10:02:30.000Z", "tu3", "npm test", isSidechain=True),
        user("2026-10-08T10:02:31.000Z", [{"type": "tool_result", "tool_use_id": "tu3", "content": [{"type": "text", "text": "Exit code 1\nmissing module"}]}], isSidechain=True),
    ])
    _jsonl(tx_dir / "s0.jsonl", [
        user("2026-10-01T09:00:00.100Z", "<command-name>/clear</command-name>"),
        user("2026-10-01T09:00:05.300Z", "how do I install the old tool here"),   # same second as the recall row: still the one before it
        user("2026-10-01T09:00:40.000Z", "a later prompt"),
    ])
    return st


def test_tune_gather_writes_evidence(tmp_path, monkeypatch, capsys):
    st = _tune_fixture(tmp_path, monkeypatch)
    iirc.main(["tune", "gather"])
    out = capsys.readouterr().out
    assert "2 sessions, 4 recalls" in out and "s1.json: 3 recalls, 2 pages suggested, 5 candidates to judge (transcript)" in out
    text = (st / "tune" / "s1.json").read_text()
    s1 = json.loads(text)
    assert len(text.splitlines()) == 2 + len(s1["recalls"])   # one recall per line
    assert s1["conditions"][0]["knobs"] == {"semantic_only": 0.28, "both": 0.34}
    r1, r2, r3 = s1["recalls"]
    assert r1["key"] == "r1" and r1["prompt"] == {"text": "why does the build fail on this machine after the upgrade", "from": "prompts file"}
    assert r1["suggested"] == [{"page": "a.md", "score": "75% match, meaning", "read_turns_later": 0},
                               {"page": "b.md", "score": "70% match, meaning+term", "read_turns_later": 1}]
    # the suggested pages, then the three refused pages nearest the larger knob (0.34) within 0.03, in rank order
    assert [(c["page"], c["distance"]) for c in r1["candidates"]] == [("a.md", 0.25), ("b.md", 0.3), ("c.md", 0.36), ("near-0.md", 0.365), ("near-1.md", 0.355)]
    assert r1["candidates_left_out"] == 2   # d.md, beyond the band, and near-2.md, the fourth nearest
    assert r1["next_tools"] == [{"tool": "Bash", "input": "iirc read a.md"}]
    assert r1["searches"] == [{"query": "build failure", "pages": ["c.md"]}] and r1["read_unsuggested"] == ["c.md"]
    assert r2["via"] == "failure" and r2["failed"]["command"] == "make build" and "boom" in r2["failed"]["error"]
    assert r2["next_tools"][0]["input"] == "make build" and r2["candidates"] == [] and r2["subagent"] is None
    # a subagent's failure logs under the parent session; its command is in the subagent's own file
    assert r3["subagent"] == "agent-x" and r3["failed"] == {"command": "npm test", "error": "Exit code 1 missing module"}
    s0 = json.loads((st / "tune" / "s0.json").read_text())
    old = s0["recalls"][0]
    assert old["key"] == "2026-10-01T09:00:05Z" and old["recall_id"] is None
    assert old["prompt"] == {"text": "how do I install the old tool here", "from": "transcript by time"}
    assert old["suggested"][0]["read_turns_later"] is None and old["candidates"] == []
    assert not (st / "tune" / "elsewhere.json").exists()


def test_tune_done_makes_gather_skip_a_session(tmp_path, monkeypatch, capsys):
    st = _tune_fixture(tmp_path, monkeypatch)
    iirc.main(["tune", "done", "s0"])
    assert "s0 is tuned" in capsys.readouterr().out
    row = iirc.read_log()[-1]
    assert (row["cmd"], row["tuned"], row["session"]) == ("tuned", "s0", "tuner")
    iirc.main(["tune", "gather"])
    assert "1 session, 3 recalls" in capsys.readouterr().out and not (st / "tune" / "s0.json").exists()
    iirc.main(["tune", "gather", "--session", "s0"])   # named, a tuned session is gathered again
    assert "1 session, 1 recalls" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        iirc.main(["tune", "done", "nope"])


def test_tune_judge_validates_and_later_lines_supersede(tmp_path, monkeypatch, capsys):
    import io
    st = _tune_fixture(tmp_path, monkeypatch)
    iirc.main(["tune", "gather"]); capsys.readouterr()
    lines = [{"session": "s1", "recall_id": "r1", "page": "a.md", "label": "noise", "note": "off topic"},
             {"session": "s0", "ts": "2026-10-01T09:00:05Z", "page": "a.md", "label": "relevant"},
             {"session": "s1", "recall_id": "r1", "page": "project/a.md", "label": "relevant", "note": "on reflection"}]
    monkeypatch.setattr("sys.stdin", io.StringIO("".join(json.dumps(x) + "\n" for x in lines)))
    iirc.main(["tune", "judge"])
    assert "recorded 3 judgments" in capsys.readouterr().out
    latest = iirc.judgments()
    assert len(latest) == 2 and latest[(str((tmp_path / "repo").resolve()), "s1", "r1", "a.md")]["label"] == "relevant"
    bad = [{"session": "s1", "recall_id": "r1", "page": "b.md", "label": "relevant"},
           {"session": "s1", "recall_id": "r9", "page": "b.md", "label": "maybe"}]
    monkeypatch.setattr("sys.stdin", io.StringIO("".join(json.dumps(x) + "\n" for x in bad)))
    with pytest.raises(SystemExit):
        iirc.main(["tune", "judge"])
    err = capsys.readouterr().err
    assert "line 2" in err and "label must be one of" in err and "no recall r9" in err
    assert len((st / "tune" / "judgments.jsonl").read_text().splitlines()) == 3   # the good line went unwritten too


def _sweep_fixture(tmp_path, monkeypatch, pairs):
    """Eval rows and judgments for (page, distance, label) pairs, all semantic only, in one recall."""
    st = _tune_fixture(tmp_path, monkeypatch)
    r = str((tmp_path / "repo").resolve())
    rows = [{"session": "s5", "repo": r, "cmd": "candidate", "recall_id": "r5", "rank": i, "page": p, "distance": d,
             "paths": ["semantic"], "rare_terms": [], "head_terms": []} for i, (p, d, _) in enumerate(pairs)]
    _jsonl(st / "eval-2026-09.jsonl", rows)
    _jsonl(st / "tune" / "judgments.jsonl", [{"repo": r, "session": "s5", "recall": "r5", "page": p, "label": label} for p, _, label in pairs]
           + [{"repo": r, "session": "s0", "recall": "2026-10-01T09:00:05Z", "page": "a.md", "label": "relevant"},
              {"repo": "/other", "session": "s5", "recall": "r5", "page": "p1.md", "label": "noise"}])


def test_tune_sweep_says_when_too_few_pairs_were_judged(tmp_path, monkeypatch, capsys):
    _sweep_fixture(tmp_path, monkeypatch, [("p1.md", 0.25, "relevant"), ("p2.md", 0.33, "noise"), ("p3.md", 0.3, "unsure")])
    iirc.main(["tune", "sweep"])
    out = capsys.readouterr().out
    assert "judged pairs with a distance: 2 (1 relevant, 1 noise)" in out
    assert "1 unsure; 1 with no candidate row" in out and "0 with no distance" in out and "1 from other repositories" in out
    assert "relevant passed 1, noise passed 0, relevant refused 0" in out
    assert "too few judged pairs to propose a change: 2, and the floor is 30" in out and "best by F1" not in out


def test_tune_sweep_finds_knobs_that_change_the_counts(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(iirc.iirc_embed.MODELS["nomic-embed-text"].knobs, "both", (0.34, 0.10, 0.60))   # the fixtures sit around this knob, not the default
    monkeypatch.setattr(iirc, "TUNE_FLOOR", 3)
    _sweep_fixture(tmp_path, monkeypatch, [("p1.md", 0.25, "relevant"), ("p2.md", 0.30, "relevant"), ("p3.md", 0.33, "noise")])
    iirc.main(["tune", "sweep"])
    out = capsys.readouterr().out
    assert "current  semantic_only 0.28 both 0.34: relevant passed 1, noise passed 0, relevant refused 1" in out
    best = out.split("best by F1:\n")[1].splitlines()[0]
    # 0.30 and 0.32 both pass the two relevant pages and refuse the noise; the smaller move wins the tie
    assert best.strip().startswith("semantic_only 0.30 both 0.34: relevant passed 2, noise passed 0, relevant refused 0")
    assert "beats the current knobs on F1 by 0.33" in out
    grid = iirc.knob_grid()
    assert len(grid) == len({(k["semantic_only"], k["both"]) for k in grid}) and all(k["both"] >= k["semantic_only"] for k in grid)


def test_knobs_set_writes_only_its_line(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    toml = tmp_path / ".claude" / "iirc.toml"
    iirc.main(["knobs", "set", "both", "0.36"])   # no file yet
    assert toml.read_text() == "[recall.nomic-embed-text]\nboth = 0.36\n"
    toml.write_text("# stores\nshow_hooks = true\n\n[stores.recall]\nkind = \"project\"\n")
    iirc.main(["knobs", "set", "semantic_only", "0.3"])   # [stores.recall] is not a [recall.MODEL] table
    assert toml.read_text() == "# stores\nshow_hooks = true\n\n[stores.recall]\nkind = \"project\"\n\n[recall.nomic-embed-text]\nsemantic_only = 0.3\n"
    toml.write_text("[recall.nomic-embed-text]  # the gate\nsemantic_only = 0.26   # measured\n\n[stores.project]\nkind = \"project\"\n")
    iirc.main(["knobs", "set", "semantic_only", "0.3"])
    iirc.main(["knobs", "set", "both", "0.4"])
    assert toml.read_text() == "[recall.nomic-embed-text]  # the gate\nsemantic_only = 0.3   # measured\nboth = 0.4\n\n[stores.project]\nkind = \"project\"\n"
    iirc.set_root(tmp_path)
    assert iirc.RECALL == {"semantic_only": 0.3, "both": 0.4}
    capsys.readouterr()
    for argv, says in ((["semantic_only", "0.9"], "from 0.1 to 0.6"), (["semantic_only", "0.45"], "set both first")):
        with pytest.raises(SystemExit):
            iirc.main(["knobs", "set", *argv])
        assert says in capsys.readouterr().err
    assert iirc.RECALL == {"semantic_only": 0.3, "both": 0.4}
    toml.unlink(); iirc.set_root(tmp_path)


def test_tune_gather_finds_the_prompt_by_hash_once_the_prompts_file_is_gone(tmp_path, monkeypatch, capsys):
    st = _tune_fixture(tmp_path, monkeypatch)
    (st / "prompts" / "s1.jsonl").unlink()
    iirc.main(["tune", "gather", "--session", "s1"])
    r1 = json.loads((st / "tune" / "s1.json").read_text())["recalls"][0]
    assert r1["prompt"]["from"] == "transcript by hash" and r1["prompt"]["text"].startswith("why does the build fail")


def test_read_transcript_keeps_a_prompt_typed_twice_and_merges_a_queued_one(tmp_path):
    def user(ts, text):
        return {"type": "user", "timestamp": ts, "message": {"content": text}}
    queued = {"type": "attachment", "timestamp": "2026-10-08T10:10:00.000Z",
              "attachment": {"type": "queued_command", "prompt": "while you work, check the log", "commandMode": "prompt"}}
    path = tmp_path / "t.jsonl"
    _jsonl(path, [user("2026-10-08T10:00:00.000Z", "yes"), user("2026-10-08T10:00:30.000Z", "yes"),
                  queued, user("2026-10-08T10:10:01.000Z", "while you work, check the log")])
    assert [p["text"] for p in iirc.read_transcript(path)["prompts"]] == ["yes", "yes", "while you work, check the log"]


def test_tune_gather_joins_a_repeated_prompt_to_its_last_occurrence(tmp_path, monkeypatch, capsys):
    st = _tune_fixture(tmp_path, monkeypatch)
    r = str((tmp_path / "repo").resolve())
    again = "run the full test suite again and tell me what failed"
    _jsonl(st / "log.jsonl", [
        {"ts": "2026-10-08T11:01:40Z", "session": "s2", "repo": r, "cmd": "recall", "via": "prompt", "pages": [], "recall_id": "q1", "prompt_hash": iirc.prompt_hash(again)},
        {"ts": "2026-10-08T11:05:00Z", "session": "s2", "repo": r, "cmd": "recall", "via": "prompt", "pages": [], "recall_id": "q2", "prompt_hash": iirc.prompt_hash(again)},
    ])
    tx = tmp_path / "claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", r) / "s2.jsonl"

    def user(ts, text):
        return {"type": "user", "timestamp": ts, "message": {"content": text}}

    def tool(ts, command):
        return {"type": "assistant", "timestamp": ts, "message": {"content": [{"type": "tool_use", "id": command, "name": "Bash", "input": {"command": command}}]}}
    _jsonl(tx, [user("2026-10-08T11:01:40.000Z", again), tool("2026-10-08T11:01:45.000Z", "first run"),
                user("2026-10-08T11:05:00.000Z", again), tool("2026-10-08T11:05:05.000Z", "second run")])
    iirc.main(["tune", "gather", "--session", "s2"])
    q1, q2 = json.loads((st / "tune" / "s2.json").read_text())["recalls"]
    assert q1["prompt"]["from"] == q2["prompt"]["from"] == "transcript by hash"
    assert [t["input"] for t in q1["next_tools"]] == ["first run"] and [t["input"] for t in q2["next_tools"]] == ["second run"]


def test_tune_judge_refuses_a_page_the_recall_never_listed(tmp_path, monkeypatch, capsys):
    import io
    st = _tune_fixture(tmp_path, monkeypatch)
    iirc.main(["tune", "gather"]); capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session": "s1", "recall_id": "r1", "page": "a-typo.md", "label": "noise"}) + "\n"))
    with pytest.raises(SystemExit):
        iirc.main(["tune", "judge"])
    assert "line 1: recall r1 lists no page a-typo.md" in capsys.readouterr().err
    assert not (st / "tune" / "judgments.jsonl").exists()


def test_tune_gather_skips_rows_that_are_not_objects(tmp_path, monkeypatch, capsys):
    st = _tune_fixture(tmp_path, monkeypatch)
    for f in (st / "log.jsonl", st / "eval-2026-10.jsonl", st / "prompts" / "s1.jsonl"):
        f.write_text(f.read_text() + "42\n[1, 2]\n\"text\"\n")
    iirc.main(["tune", "gather"])
    assert "2 sessions, 4 recalls" in capsys.readouterr().out


def test_read_for_tune_logs_apart_from_the_sessions_reads(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s11")
    (tmp_path / ".iirc").mkdir(); (tmp_path / ".iirc" / "a.md").write_text("---\ntitle: A\n---\nx\n"); iirc.set_root(tmp_path)
    monkeypatch.setattr(iirc, "tool", lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    iirc.main(["read", "--for-tune", "a.md"]); iirc.main(["read", "a.md"])
    assert [r["cmd"] for r in iirc.read_log(session="s11")] == ["tune_read", "read"]
    assert iirc.session_summary("s11")["read"] == ["a.md"]


def test_knobs_set_finds_a_header_with_spaces_inside_the_brackets(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    toml = tmp_path / ".claude" / "iirc.toml"; toml.parent.mkdir()
    toml.write_text('[ recall . "nomic-embed-text" ]\nboth = 0.36\n')
    iirc.main(["knobs", "set", "both", "0.38"])
    assert toml.read_text() == '[ recall . "nomic-embed-text" ]\nboth = 0.38\n'
    toml.unlink(); iirc.set_root(tmp_path)


def test_worth_judging_takes_one_page_past_max_suggested():
    knobs = {"semantic_only": 0.28, "both": 0.34}
    cands = [{"page": "a.md", "verdict": "passed", "distance": 0.2}, {"page": "b.md", "verdict": "over_max", "distance": 0.22},
             {"page": "c.md", "verdict": "over_max", "distance": 0.23}, {"page": "d.md", "verdict": "too_far", "distance": 0.35}]
    assert [c["page"] for c in iirc.worth_judging(cands, knobs)] == ["a.md", "b.md", "d.md"]


def test_show_returns_the_page_as_json_and_is_not_the_agents_read(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s12")
    field = tmp_path / ".iirc"; field.mkdir()
    (field / "a.md").write_text("---\ntitle: A\nsummary: s\ntopics: [x]\nkind: finding\n---\nSee [[b]] and [[gone]].\n")
    (field / "b.md").write_text("---\ntitle: B\n---\nb\n")
    iirc.set_root(tmp_path)
    iirc.main(["show", "a.md"])
    out = json.loads(capsys.readouterr().out)
    assert (out["name"], out["store"], out["fm"]["title"]) == ("a.md", "project", "A")
    assert out["body"].startswith("See [[b]]") and out["links"] == ["b.md"] and out["signals"] == []
    assert [r["cmd"] for r in iirc.read_log(session="s12")] == ["show"]
    assert iirc.session_summary("s12")["read"] == []


# p5 step 16
def test_skill_names_the_writing_rules():
    """SKILL.md carries research DQ5-A's five rules for writing a page the search can find."""
    text = " ".join((ROOT / "skills" / "iirc" / "SKILL.md").read_text().lower().split())
    rules = ["write for the search", "words a future prompt or error will use", "quote error text exactly",
             "search before every write", "names the page it reverses", "where the fact holds"]
    assert [r for r in rules if r not in text] == []


# p5 step 1

def test_tune_sweep_replay_counts_passes(tmp_path, monkeypatch, capsys):
    monkeypatch.setitem(iirc.iirc_embed.MODELS["nomic-embed-text"].knobs, "both", (0.34, 0.10, 0.60))   # the fixtures sit around this knob, not the default
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(iirc, "TUNE_FLOOR", 3)
    field = tmp_path / ".iirc"; field.mkdir()
    for name, title in (("pysqlite3-install-override.md", "pysqlite3-binary blocks install"), ("uv-install-notes.md", "uv install notes"),
                        ("ollama-host-hang.md", "ollama on 11434 hangs"), ("quiet.md", "quiet page")):
        (field / name).write_text(f"---\ntitle: {title}\nsummary: s\ntopics: [t]\nkind: finding\n---\nx\n")
    iirc.write_config_file({"semantic": False})
    r = str(tmp_path.resolve())
    q1 = {"repo": r, "qid": "q1", "prompt": "why does uv tool install fail with pysqlite3-binary", "via": "prompt"}
    q2 = {"repo": r, "qid": "q2", "prompt": "curl 127.0.0.1:11434 hangs", "via": "failure", "excerpt": True}
    _jsonl(tmp_path / "a.jsonl", [{**q1, "page": "pysqlite3-install-override.md", "label": "relevant"},   # an identifier passes
                                  {**q1, "page": "uv-install-notes.md", "label": "noise"},                # a plain word is refused
                                  {**q1, "page": "gone.md", "label": "noise"}])                           # not in the store
    _jsonl(tmp_path / "b.jsonl", [{**q2, "page": "ollama-host-hang.md", "label": "noise"},
                                  {**q2, "page": "quiet.md", "label": "relevant"},                        # search never finds it
                                  {**q2, "page": "uv-install-notes.md", "label": "unsure"},
                                  {**q1, "repo": "/other", "page": "pysqlite3-install-override.md", "label": "noise"}])
    calls = []
    real = iirc.hybrid_search
    monkeypatch.setattr(iirc, "hybrid_search", lambda q: calls.append(q) or real(q))
    iirc.main(["tune", "sweep", "--replay", str(tmp_path / "a.jsonl"), str(tmp_path / "b.jsonl")])
    out = capsys.readouterr().out
    assert len(calls) == 2   # one search per prompt, none for another repository's
    assert "judged pairs: 4 (2 relevant, 2 noise) from 2 prompts; 2 of them from excerpts" in out
    assert "left out: 1 unsure; 1 missing from the store; 1 from other repositories" in out
    assert "current  semantic_only 0.28 both 0.34: relevant passed 1, noise passed 1, relevant refused 1; precision 0.50, recall 0.50, F1 0.50" in out
    assert "best by F1:" in out and "no grid point beats the current knobs on F1" in out


# p5 step 14


def test_read_leads_with_the_page(tmp_path, monkeypatch, capsys):
    import subprocess
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    sha = _repo(tmp_path)
    field = tmp_path / ".iirc"; field.mkdir(); iirc.set_root(tmp_path)
    (field / "cited.md").write_text(
        f"---\ntitle: Cited page\nsummary: s\nkind: finding\nrefs:\n- docs/a.md@{sha}\nuuid: 1f1ae15b-0761\n"
        "created: '2026-09-01T00:00:00Z'\nupdated: '2026-09-02T00:00:00Z'\nverified: '2026-09-19T00:00:00Z'\n---\nWhat is true.\n\n## Sources\n- x\n")
    (tmp_path / "docs" / "a.md").write_text("two\n")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qam", "two"], check=True)
    # the tool's read prints the raw page; the wrapper must not need it for a page it can parse
    monkeypatch.setattr(iirc, "tool", lambda *a, **k: type("P", (), {"returncode": 0, "stdout": (field / a[-1]).read_text(), "stderr": ""})())
    iirc.main(["read", "cited.md"])
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert out.startswith(iirc.READ_HEAD) and lines[1] == "cited.md: Cited page"
    assert lines[2].startswith("suspect: docs/a.md changed since cited")
    assert lines[3] == "What is true."
    assert f"refs: docs/a.md@{sha} · verified 2026-09-19" in lines
    assert "uuid:" not in out and "created:" not in out and "updated:" not in out
    assert lines[-1] == "wrong or stale? `iirc write cited.md` replaces it, `iirc delete cited.md` removes it; still right? `iirc verify cited.md`."


def test_read_footer_write_names_the_store(tmp_path, monkeypatch, capsys):
    project, agent = _two_stores(tmp_path, monkeypatch)
    _page(project.dir, "p.md"); _page(agent.dir, "a.md")
    # write takes a bare name and --store; delete and verify take STORE/PAGE
    iirc.main(["read", "agent/a.md"])
    assert capsys.readouterr().out.splitlines()[-1] == (
        "wrong or stale? `iirc write a.md --store agent` replaces it, `iirc delete agent/a.md` removes it; still right? `iirc verify agent/a.md`.")
    iirc.main(["read", "p.md"])
    assert capsys.readouterr().out.splitlines()[-1] == (
        "wrong or stale? `iirc write p.md` replaces it, `iirc delete project/p.md` removes it; still right? `iirc verify project/p.md`.")
    iirc.main(["read", "p.md", "agent/a.md"])
    assert capsys.readouterr().out.splitlines()[-1].endswith(
        "where PAGE is project/p.md or agent/a.md; write takes `p.md` or `a.md --store agent`.")


# p5 step 3

def _line_replay():
    loader = SourceFileLoader("line_replay", str(ROOT / "scripts" / "line-replay.py"))
    spec = importlib.util.spec_from_loader("line_replay", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


# p5 step 2

def test_secret_patterns_anchor_at_a_word():
    def hits(text):
        return [name for name, pattern in iirc.SECRET_PATTERNS.items() if pattern.search(text)]
    token = "sk-" + "Ab3dEf6hIj9kLm2nOp5qRs8t"   # built in two parts so no scanner takes the file for a leak
    assert len(hits(f"key: {token}")) == 1
    assert hits("ghp_" + "a1B2" * 9) and hits("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert hits("task-notification-something-long-enough") == []
    assert hits("risk-" + "x" * 30) == [] and hits("my_sk-" + "x" * 30) == []


def _replay_files():
    loader = SourceFileLoader("replay_files", str(ROOT / "scripts" / "replay-files.py"))
    spec = importlib.util.spec_from_loader("replay_files", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def test_line_replay_counts_reads(tmp_path):
    lr = _line_replay()
    replay = tmp_path / "replay.jsonl"
    rows = [{"repo": str(tmp_path), "qid": "q1", "prompt": "why does recall time out?", "via": "prompt", "page": p, "label": l}
            for p, l in [("hook-timeout.md", "relevant"), ("host-hang.md", "noise"), ("maybe.md", "unsure")]]
    replay.write_text("".join(json.dumps(r) + "\n" for r in rows))
    labels = lr.load_replay(replay)[(str(tmp_path), "q1")]["labels"]

    def bash(cmd):
        return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]}})
    stream = "\n".join([
        json.dumps({"type": "system", "subtype": "init"}),
        bash("iirc read hook-timeout.md"),
        bash("iirc read project/host-hang && iirc read unlabelled.md"),
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "iirc read host-hang.md"},
                                                                 {"type": "tool_use", "name": "Read", "input": {"file_path": ".iirc/host-hang.md"}}]}}),
        bash("iirc pull hook-timeout"),
        bash("iirc pull ollama keep_alive"),
        bash("git status"),
        "not json",
    ])
    counts = lr.count_reads(stream, labels)
    assert (counts["relevant"], counts["noise"], counts["other"], counts["pulls"]) == (2, 1, 1, 1)
    assert counts["pages"] == {"hook-timeout.md": 2, "host-hang.md": 1, "unlabelled.md": 1}


def test_replay_files_join_labels_to_prompts():
    rf = _replay_files()
    prompts = rf.neckbeard_prompts([
        {"session": "aaaaaaaa-1111", "uuid": "bbbbbbbb-2222", "text": "why is the vm down? " + "sk-" + "x" * 24},
        {"session": "cccccccc-3333", "uuid": "dddddddd-4444", "text": "y" * 9000},
    ])
    labels = [{"qid": "aaaaaaaa/bbbbbbbb", "page": "vm.md", "label": "relevant"},
              {"qid": "cccccccc/dddddddd", "page": "long.md", "label": "noise"},
              {"qid": "eeeeeeee/ffffffff", "page": "gone.md", "label": "noise"}]
    rows, missing = rf.join(labels, prompts, "/repo")
    assert missing == ["eeeeeeee/ffffffff"]
    assert rows[0] == {"repo": "/repo", "qid": "aaaaaaaa/bbbbbbbb", "prompt": "why is the vm down? [REDACTED]",
                       "via": "prompt", "page": "vm.md", "label": "relevant"}
    assert len(rows[1]["prompt"]) == 8000 and "excerpt" not in rows[1]

    # agent-builder: the transcript by hash first, then by the excerpt, else the excerpt itself
    tx = [{"ts": 10.0, "hash": iirc.prompt_hash("full\ntext"), "text": "full\ntext"},
          {"ts": 20.0, "hash": "h2", "text": "second\nprompt " + "z" * 400}]
    assert rf.recall_prompt({"via": "prompt", "ts": "x", "prompt": {"text": "nope"}}, iirc.prompt_hash("full\ntext"), tx) \
        == {"prompt": "full\ntext", "via": "prompt"}
    excerpt = iirc.clean(tx[1]["text"], 300)
    assert rf.recall_prompt({"via": "prompt", "prompt": {"text": excerpt}}, None, tx)["prompt"] == tx[1]["text"]
    assert rf.recall_prompt({"via": "prompt", "prompt": {"text": "lost"}}, None, tx) == {"prompt": "lost", "via": "prompt", "excerpt": True}
    assert rf.recall_prompt({"via": "failure", "failed": {"command": "make", "error": "boom"}}, None, None) == {"prompt": "make\nboom", "via": "failure"}
    assert rf.recall_prompt({"via": "prompt", "prompt": {"text": None}}, None, None) is None
    rows, _ = rf.join([{"qid": "q", "page": "p.md", "label": "unsure"}], {"q": {"prompt": "lost", "via": "prompt", "excerpt": True}}, "/r")
    assert rows[0]["excerpt"] is True


# p5 step 15

def _write_page(monkeypatch, tmp_path, name, title, summary, body):
    import io
    project, _ = _two_stores(tmp_path, monkeypatch)
    monkeypatch.setattr(iirc, "tool", _fake_tool(project.dir))
    monkeypatch.setattr(iirc, "reindex", lambda **k: None)
    monkeypatch.setattr("sys.stdin", io.StringIO(body))
    iirc.main(["write", name, "--title", title, "--summary", summary, "--topics", "t", "--kind", "finding"])
    return project.dir / name


def test_write_refuses_secrets(tmp_path, monkeypatch, capsys):
    token = "ghp_" + "Zx9Yw8" * 6   # built in two parts so no scanner takes the file for a leak
    with pytest.raises(SystemExit):
        _write_page(monkeypatch, tmp_path, "leak.md", "Leak", "a leak", f"one\ntwo {token}\n\n## Sources\n\n- y\n")
    err = capsys.readouterr().err
    assert not (tmp_path / ".iirc" / "leak.md").exists()
    assert "github token" in err and "line 9" in err and token not in err and "ghp_" not in err


def test_write_warns_and_succeeds(tmp_path, monkeypatch, capsys):
    page = _write_page(monkeypatch, tmp_path, "shape.md", "Ollama unloads the embedding model after five minutes of idle time here",
                       "2026-10-09 we saw the hook stall", "x\n\n## Sources\n\n- y\n")
    assert page.is_file()
    warnings = [line for line in capsys.readouterr().err.splitlines() if line.startswith("iirc: warning:")]
    assert len(warnings) == 3, warnings
    assert "date" in warnings[0] and "70" in warnings[1] and "title" in warnings[2]
    _write_page(monkeypatch, tmp_path, "fine.md", "Ollama unloads the model", "Ollama unloads the embed model after idle time", "x\n\n## Sources\n\n- y\n")
    assert "warning" not in capsys.readouterr().err
    _write_page(monkeypatch, tmp_path, "decided.md", "Search uses rare terms", "Creator decision: search uses rare terms", "x\n\n## Sources\n\n- y\n")
    assert "Creator decision" in capsys.readouterr().err


# p5 step 19

def test_doctor_brief_calls_git_once_per_sha(tmp_path, monkeypatch, capsys):
    field = _project(tmp_path, monkeypatch)
    iirc.main(["setup", "--substring"]); capsys.readouterr()
    docs = tmp_path / "docs"
    for name in ("b.md", "c.md"):
        (docs / name).write_text(f"{name}\n\n## Alpha\n\nalpha\n")
    _git(tmp_path, "add", "docs"); _git(tmp_path, "commit", "-qm", "b c")
    first = _git(tmp_path, "log", "-1", "--format=%h").strip()
    (docs / "d.md").write_text("d\n"); _git(tmp_path, "add", "docs"); _git(tmp_path, "commit", "-qm", "d")
    second = _git(tmp_path, "log", "-1", "--format=%h").strip()
    _page(field, "p1.md", extra=f"refs:\n- docs/a.md@{first}\n- docs/b.md@{first}\n")
    _page(field, "p2.md", extra=f"refs:\n- docs/c.md#Alpha@{first}\n- docs/a.md@{second}\n")
    _page(field, "p3.md", extra=f"refs:\n- docs/d.md@{second}\n- docs/b.md@{second}\n")
    calls: list[list[str]] = []
    real = iirc.subprocess.run

    def counting(argv, *a, **k):
        if isinstance(argv, list) and argv[:1] == ["git"]:
            calls.append(argv)
        return real(argv, *a, **k)
    monkeypatch.setattr(iirc.subprocess, "run", counting)
    iirc.main(["doctor", "--brief"])
    assert "suspect" not in capsys.readouterr().out
    per_sha = {sha: sum(any(sha in arg for arg in argv) for argv in calls) for sha in (first, second)}
    assert per_sha == {first: 1, second: 1}


# p5 step 20


def test_read_unsuggested_skips_maintenance_reads(tmp_path, monkeypatch, capsys):
    st = _tune_fixture(tmp_path, monkeypatch)
    r = str((tmp_path / "repo").resolve())
    # the 10:00:30 read of c.md, then a write of it within five minutes: the read was for the write, not for guidance
    with (st / "log.jsonl").open("a") as f:
        f.write(json.dumps({"ts": "2026-10-08T10:04:00Z", "session": "s1", "repo": r, "cmd": "write", "page": "project/c.md", "kind": "finding"}) + "\n")
    iirc.main(["tune", "gather", "--session", "s1"])
    r1 = json.loads((st / "tune" / "s1.json").read_text())["recalls"][0]
    assert r1["read_unsuggested"] == []


def test_gather_skips_the_tuning_window(tmp_path, monkeypatch, capsys):
    import io
    st = _tune_fixture(tmp_path, monkeypatch)
    r = str((tmp_path / "repo").resolve())

    def recall(ts, rid):
        return {"ts": ts, "session": "tuner", "repo": r, "cmd": "recall", "via": "prompt", "pages": [], "recall_id": rid}
    # recalls before the first gather and after the last judge are work; the ones between are about tuning
    _jsonl(st / "log-2026-09.jsonl", [
        recall("2026-10-08T12:00:00Z", "t1"),
        {"ts": "2026-10-08T12:01:00Z", "session": "tuner", "repo": r, "cmd": "tune_gather"},
        recall("2026-10-08T12:02:00Z", "t2"),
        {"ts": "2026-10-08T12:05:00Z", "session": "tuner", "repo": r, "cmd": "tune_judge", "judged": 1},
        recall("2026-10-08T12:10:00Z", "t3"),
    ])
    _jsonl(st / "prompts" / "tuner.jsonl", [{"ts": "2026-10-08T12:00:00Z", "prompt_hash": "x", "excerpt": "real work", "recall_id": "t1"}])
    iirc.main(["tune", "gather"])
    assert "3 sessions" in capsys.readouterr().out
    assert [x["key"] for x in json.loads((st / "tune" / "tuner.json").read_text())["recalls"]] == ["t1", "t3"]
    assert iirc.read_log()[-1]["cmd"] == "tune_gather"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session": "s1", "recall_id": "r1", "page": "a.md", "label": "noise"}) + "\n"))
    iirc.main(["tune", "judge"]); capsys.readouterr()
    assert iirc.read_log()[-1]["cmd"] == "tune_judge" and "tuning" not in {x["cmd"] for x in iirc.read_log()}
    iirc.main(["tune", "gather"])   # the last judge now follows t3
    assert [x["key"] for x in json.loads((st / "tune" / "tuner.json").read_text())["recalls"]] == ["t1"]


# p5 step 21


def test_base_adds_md():
    assert iirc.base("project/a") == iirc.base("a.md") == iirc.base("project/a.md") == "a.md"


def test_gather_time_join_within_five_seconds(tmp_path, monkeypatch, capsys):
    st = _tune_fixture(tmp_path, monkeypatch)
    r = str((tmp_path / "repo").resolve())
    # recalls from before prompt hashes: the first comes 30 s after its nearest prompt, the second 4 s after
    _jsonl(st / "log-2026-09.jsonl", [
        {"ts": "2026-10-08T11:00:30Z", "session": "s4", "repo": r, "cmd": "recall", "via": "prompt", "pages": []},
        {"ts": "2026-10-08T11:02:04Z", "session": "s4", "repo": r, "cmd": "recall", "via": "prompt", "pages": []},
    ])
    tx = tmp_path / "claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", r) / "s4.jsonl"
    _jsonl(tx, [{"type": "user", "timestamp": "2026-10-08T11:00:00.000Z", "message": {"content": "a subagent's hand-back, long before"}},
                {"type": "user", "timestamp": "2026-10-08T11:02:00.000Z", "message": {"content": "the prompt this recall searched"}}])
    iirc.main(["tune", "gather", "--session", "s4"])
    far, near = json.loads((st / "tune" / "s4.json").read_text())["recalls"]
    assert far["prompt"] == {"text": None, "from": None}
    assert near["prompt"] == {"text": "the prompt this recall searched", "from": "transcript by time"}


def test_failure_recall_keeps_its_error(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude")); monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "f1")
    (tmp_path / ".iirc").mkdir(); iirc.set_root(tmp_path)
    monkeypatch.setattr(iirc, "hybrid_search", lambda q: [])
    error = "Exit code 1\nError: Cannot find module 'leftpad' " + "at require " * 60
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "npm test"}, "error": error})))
    iirc.main(["recall", "--failure"])
    # no transcript: the prompts file alone fills the evidence
    iirc.main(["tune", "gather", "--session", "f1"])
    failed = json.loads((tmp_path / "st" / "dokidlc-iirc" / "tune" / "f1.json").read_text())["recalls"][0]["failed"]
    assert failed["command"] == "npm test"
    assert failed["error"].startswith("Error: Cannot find module 'leftpad'") and 250 < len(failed["error"]) <= 300


def test_gather_skips_recordings(tmp_path, monkeypatch, capsys):
    st = _tune_fixture(tmp_path, monkeypatch)
    r = str((tmp_path / "repo").resolve())
    monkeypatch.setenv("IIRC_RECORDING", "1")
    conds = iirc.conditions("semantic", 5)
    assert conds["recording"] is True
    _jsonl(st / "log-2026-09.jsonl", [
        {"ts": "2026-10-08T11:00:00Z", "session": "rec", "repo": r, "cmd": "start", **conds},
        {"ts": "2026-10-08T11:00:30Z", "session": "rec", "repo": r, "cmd": "recall", "via": "prompt", "pages": [], "recall_id": "v1"},
    ])
    _jsonl(st / "prompts" / "rec.jsonl", [{"ts": "2026-10-08T11:00:30Z", "prompt_hash": "x", "excerpt": "a demo prompt", "recall_id": "v1"}])
    iirc.main(["tune", "gather"])
    assert "2 sessions" in capsys.readouterr().out and not (st / "tune" / "rec.json").exists()
    monkeypatch.delenv("IIRC_RECORDING")
    assert "recording" not in iirc.conditions("semantic", 5)


# p5 step 5


def test_string_search_ignores_sources_and_links(tmp_path):
    field = tmp_path / ".iirc"; field.mkdir()
    (field / "cited.md").write_text("---\ntitle: Recall timeouts\nsummary: the hook waits\n---\n"
                                    "The hook gives up after five seconds.\n\n## Sources\n\n- bin/iirc recall_hook, read 2026-10-01\n")
    (field / "linker.md").write_text("---\ntitle: Ollama unloads\nsummary: keep_alive\n---\nSee [[keepalive-trap|the trap page]] and [[hook-budget]].\n")
    (field / "plain.md").write_text("---\ntitle: Budget\nsummary: a limit\n---\nThe recall_hook budget is five seconds.\n\n## Sources\n\n- none\n")
    (field / "hook-budget.md").write_text("---\ntitle: Hook budget\nsummary: the limit\n---\nx\n")
    iirc.set_root(tmp_path)
    assert [r["filename"] for r in iirc.string_search(["recall_hook"])] == ["plain.md"]   # in cited.md only under Sources
    assert [r["filename"] for r in iirc.string_search(["keepalive-trap", "trap", "hook-budget"])] == ["hook-budget.md"]   # in linker.md only inside links; a head still counts
    assert sorted(r["filename"] for r in iirc.string_search(["five"])) == ["cited.md", "plain.md"]   # the body before Sources still counts


# p5 step 6


def test_rarity_by_share_and_common_words(tmp_path):
    knobs = {"semantic_only": 0.28, "both": 0.34}
    # a plain English head word is never strong, however rare it is in the store
    assert iirc.gate(["semantic", "people"], 0.33, ["people"], ["people"], knobs) == (None, "needs_term")
    assert iirc.gate(["semantic", "pysqlite3"], 0.33, ["pysqlite3"], [], knobs) == ("meaning+term", None)
    assert iirc.gate(["semantic", "ollama"], 0.33, ["ollama"], ["ollama"], knobs) == ("meaning+term", None)
    assert len(iirc.COMMON_WORDS) == 1000 and "people" in iirc.COMMON_WORDS
    # 20 pages: rare is at most max(2, round(20 * 0.10)) = 2 pages; the old cut let 6 through
    field = tmp_path / ".iirc"; field.mkdir()
    for i in range(20):
        words = ["zebrafish"] * (i < 2) + ["quokka"] * (i < 3)
        (field / f"p{i:02}.md").write_text(f"---\ntitle: Page {i}\nsummary: s\n---\n{' '.join(words)}\n")
    iirc.set_root(tmp_path)
    rare = {r["filename"]: r["rare_terms"] for r in iirc.string_search(["zebrafish", "quokka"])}
    assert rare == {"p00.md": ["zebrafish"], "p01.md": ["zebrafish"], "p02.md": []}


# p5 step 22


def test_tests_leave_no_cache_dirs(_real_cache, tmp_path_factory):
    """Last in the file, so every test before it had its chance to leak."""
    real, before = _real_cache
    assert iirc.cache_dir() == Path(os.environ["IIRC_CACHE_DIR"])

    def this_run(name):
        # another checkout's tests may run at the same time; only a field under this run's temp root is a leak from here
        with contextlib.suppress(OSError):
            return str(tmp_path_factory.getbasetemp()) in (real / name / "config.toml").read_text()
        return False
    assert [n for n in {p.name for p in real.glob("test-*")} - before if this_run(n)] == []


# p5 step 3, supervisor fix: the sample holds only prompts recall would search
def test_line_replay_samples_only_prompts_recall_searches(tmp_path):
    lr = _line_replay()
    replay = tmp_path / "replay.jsonl"
    rows = [{"repo": str(tmp_path), "qid": q, "prompt": t, "via": "prompt", "page": "a.md", "label": "relevant"}
            for q, t in [("human", "why does the recall hook time out when ollama unloads the model?"),
                         ("machine", '<agent-message from="x">a hand-back about the recall hook timing out</agent-message>'),
                         ("short", "yes")]]
    replay.write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert [p["qid"] for p in lr.sample(lr.load_replay(replay), None, 1)] == ["human"]



# p5 step 8

def test_failure_recall_needs_meaning_and_term(tmp_path, monkeypatch):
    knobs = {"semantic_only": 0.28, "both": 0.34}
    meaning = (["semantic"], 0.2, [], [])
    both = (["semantic", "term"], 0.3, ["11434"], [])
    term = (["term"], None, ["11434"], [])
    assert [iirc.gate(*c, knobs, "prompt")[0] for c in (meaning, both, term)] == ["meaning", "meaning+term", "term"]
    assert [iirc.gate(*c, knobs, "failure") for c in (meaning, both, term)] == [(None, "failure_needs_both"), ("meaning+term", None), (None, "failure_needs_both")]
    # one page on a failure, whatever cap the caller asks for
    rows = [{"filename": f"{c}.md", "via": ["semantic", "term"], "distance": 0.2, "rare_terms": ["11434"]} for c in "ab"]
    assert [r["verdict"] for r in iirc.recall_verdicts(rows, knobs, cap=5, source="failure")] == ["passed", "over_max"]
    assert [r["verdict"] for r in iirc.recall_verdicts(rows, knobs, cap=5, source="prompt")] == ["passed", "passed"]
    # the eval sweep gates each candidate by its recall's via
    cand = {"paths": ["semantic"], "distance": 0.2, "rare_terms": [], "head_terms": []}
    assert iirc.sweep_counts([({**cand, "via": "prompt"}, True), ({**cand, "via": "failure"}, True)], knobs)["relevant_passed"] == 1
    # the hook's failure recall names one page, and only a meaning+term one
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s8"); iirc.set_root(tmp_path)
    monkeypatch.setattr(iirc, "hybrid_search", lambda q: [{"filename": "near.md", "via": ["semantic"], "distance": 0.1, "summary": "s", "fm": {}}]
                        + [{**r, "summary": "s", "fm": {}} for r in rows])
    line = iirc.run_recall("curl 127.0.0.1:11434 hangs", "failure", {}, failed=("curl", "hangs"))
    assert line.count("`iirc read ") == 1 and "a.md" in line and "near.md" not in line


def test_string_only_failure_recall_keeps_the_term_rule(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    knobs = {"semantic_only": 0.28, "both": 0.34}
    terms = [{"filename": f"{c}.md", "via": ["term"], "rare_terms": ["pysqlite3-binary"]} for c in "ab"]
    near = [{"filename": "near.md", "via": ["semantic"], "distance": 0.1}]
    iirc.write_config_file({"semantic": False})
    # no semantic search can make a meaning hit, so an identifier still passes, one page
    assert [r["verdict"] for r in iirc.recall_verdicts(terms, knobs, source="failure")] == ["passed", "over_max"]
    iirc.write_config_file({"semantic": True})
    assert [r["verdict"] for r in iirc.recall_verdicts(near + terms, knobs, source="failure")] == ["failure_needs_both"] * 3


# p5 step 17

def _audit_fixture(tmp_path, monkeypatch):
    """A store with one page per audit check, a clean page, and near misses; returns the vectors a stub index would give."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    field = tmp_path / ".iirc"; field.mkdir()
    token = "ghp_" + "Zx9Yw8" * 6   # built in two parts so no scanner takes the file for a leak

    def page(name, title, body="One fact.\n", summary=None, extra=""):
        (field / name).write_text(f"---\ntitle: {title}\nsummary: {summary or title}\ntopics: [t]\nkind: finding\n{extra}---\n{body}\n## Sources\n\n- x\n")
    page("clean.md", "Pelican feeders refill hourly")
    page("long.md", "Wombat burrows collapse after heavy rain when the soil holds too much clay underneath",
         summary="2026-10-09 wombat burrows collapse in rain")
    page("leak.md", "Narwhal token rotation", body=f"The token was {token} once.\n")
    page("aa-decoy.md", "Quokka zebrafish ledger")
    page("zz-target.md", "Quokka zebrafish ledger")   # the decoy's name sorts first, so its own title ranks the decoy first
    page("hub.md", "Axolotl hatchery schedule")
    page("few.md", "Ibex grazing rota")                # noise only, but under six judgments
    page("old.md", "Marmot tunnel layout", body="Replaced by [[marmot-tunnels]].\n\nThe east tunnel ran north.\n\nThe west tunnel ran south.\n")
    page("brief-old.md", "Lemur perch height", body="Superseded by [[lemur-perches]].\n\nThe perch stood at two metres.\n")
    page("prose.md", "Gecko lamp wiring", body="The old switch was replaced by a dimmer.\n\nThe lamp sits left.\n\nThe cord runs under it.\n")   # prose, no link
    page("marked.md", "Tapir pen gates", extra="superseded: tapir-pens.md\n", body="The gates opened inward.\n\nThe pens held two tapirs.\n")
    iirc.write_config_file({"semantic": False})
    r = str(tmp_path.resolve())
    _jsonl(tmp_path / "st" / "dokidlc-iirc" / "tune" / "judgments.jsonl",
           [{"repo": r, "session": "s", "recall": f"r{i}", "page": "hub.md", "label": "noise" if i < 6 else "relevant"} for i in range(8)]
           + [{"repo": r, "session": "s", "recall": f"r{i}", "page": "few.md", "label": "noise"} for i in range(5)]
           + [{"repo": "/other", "session": "s", "recall": f"r{i}", "page": "clean.md", "label": "noise"} for i in range(9)])
    near = [0.96, 0.28, 0.0]
    vectors = {p.name: [0.0, 0.0, 1.0] for p in field.glob("*.md")}
    vectors.update({"hub.md": [1.0, 0.0, 0.0], "few.md": near, "clean.md": near})
    return vectors


def test_audit_finds_each_check(tmp_path, monkeypatch, capsys):
    vectors = _audit_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(iirc, "page_vectors", lambda: vectors)
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    iirc.main(["audit"])
    out = capsys.readouterr().out
    lines = out.splitlines()
    found = {tuple(line.split(": ", 2)[:2]) for line in lines[:-1]}
    assert found == {("long.md", "title"), ("long.md", "summary"), ("leak.md", "secret"), ("zz-target.md", "own-title"),
                     ("hub.md", "hub"), ("old.md", "superseded"), ("marked.md", "superseded")}, out
    assert "ghp_" not in out
    hub = next(line for line in lines if line.startswith("hub.md: hub: "))
    # judgments alone: page-to-page distances are not on the prompt-to-page scale of the knobs
    assert hub == "hub.md: hub: noise in 6 of 8 tune judgments (75%), relevant in 2; narrow it or split it"
    assert 'says "replaced by" and keeps 2 paragraphs' in out
    assert lines[-1] == f"7 findings in 11 pages; vectors checked with {iirc.active_model().id}"
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before   # the audit never writes
    iirc.main(["audit", "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert len(rows) == 7 and all(set(r) == {"page", "check", "what", "fix"} for r in rows)
    iirc.main(["audit", "old.md"])
    assert capsys.readouterr().out.splitlines()[-1] == f"1 finding in 1 page; vectors checked with {iirc.active_model().id}"
    monkeypatch.setattr(iirc, "page_vectors", lambda: {})
    iirc.main(["audit"])
    out = capsys.readouterr().out
    assert ": own-title: " not in out and "hub.md: hub: " in out
    assert out.splitlines()[-1] == "6 findings in 11 pages; no vectors: own-title skipped"


# p5 step 18

def test_tune_sweep_prints_audit(tmp_path, monkeypatch, capsys):
    _sweep_fixture(tmp_path, monkeypatch, [("p1.md", 0.25, "relevant"), ("p2.md", 0.33, "noise")])
    field = tmp_path / "repo" / ".iirc"; field.mkdir()
    (field / "wordy.md").write_text("---\ntitle: Wombat burrows collapse after heavy rain when the soil holds too much clay underneath\n"
                                    "summary: Wombat burrows collapse in rain\ntopics: [t]\nkind: finding\n---\nx\n\n## Sources\n\n- y\n")
    flagged = "wordy.md: title: the title is 85 characters, over 70; shorten it"
    iirc.main(["tune", "sweep"])
    out = capsys.readouterr().out
    assert "\naudit:\n" in out and out.index("\naudit:\n") < out.index(flagged)
    assert out.rstrip().endswith("1 finding in 1 page; no vectors: own-title skipped")
    (tmp_path / "empty.jsonl").write_text("")
    iirc.main(["tune", "sweep", "--replay", str(tmp_path / "empty.jsonl")])
    out = capsys.readouterr().out
    assert "\naudit:\n" in out and flagged in out


# p5 step 10

def test_line_replay_counts_lost_reads(tmp_path, monkeypatch, capsys):
    lr = _line_replay()
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    log = tmp_path / "st" / "dokidlc-iirc" / "log.jsonl"
    log.parent.mkdir(parents=True)

    clock = iter(range(100))

    def ts():
        return f"2026-10-09T10:00:{next(clock):02d}Z"

    def rec(s, *pages):
        return {"ts": ts(), "session": s, "cmd": "recall", "pages": [f"{p}.md" for p in pages]}

    def read(s, page, cmd="read"):
        return {"ts": ts(), "session": s, "cmd": cmd, "pages": [page]}
    rows = [
        rec("s1", "a", "b"),
        read("s1", "proj/d"),         # STORE/PAGE and no .md: the same page as d.md
        rec("s1", "a", "c", "d"),     # a was named, d was read: both left out
        read("s1", "a"),              # a read after it was left out, with no read before it: a lost read
        rec("s1", "b"),               # left out, never read: not lost
        read("s1", "d.md", "pull"),   # d was read before it was left out: not lost
        rec("s2", "a"),               # another session starts clean
        read("s2", "a.md"),
        read("s3", "k"),              # read long before its last naming: only the session-wide read rules leave k out then
        rec("s3", "e", "k"),
        rec("s3", "f"), rec("s3", "g"), rec("s3", "h"),
        {"ts": ts(), "session": "s3", "cmd": "session", "trigger": "PreCompact"},   # only session-once resets here
        rec("s3", "e", "k"),          # e named 4 recalls back: window 5 and 10 leave it out, window 3 does not
        read("s3", "e"),
        {"ts": ts(), "session": "s3", "cmd": "write", "page": "e.md"},   # upkeep: lost, but not a plain cost
    ]
    log.write_text("".join(json.dumps(r) + "\n" for r in rows) + "not json\n")
    out = tmp_path / "repeats.json"
    assert lr.main(["--repeats", "--out", str(out)]) == 0
    assert json.loads(out.read_text())["rule"] == "session-once"   # the rule that shipped is the default
    capsys.readouterr()
    assert lr.main(["--repeats", "--rule", "window10", "--out", str(out)]) == 0
    result = json.loads(out.read_text())
    t = result["totals"]
    assert (t["recalls"], t["suggested"], t["suppressed"], t["lost_reads"], t["lost_pairs"], t["plain_pairs"]) == (9, 14, 6, 2, 2, 1)
    assert [(c["session"], c["page"]) for c in result["lost"]] == [("s1", "a.md"), ("s3", "e.md")]
    assert result["sessions"]["s1"]["suppressed"] == 3 and result["sessions"]["s2"]["suppressed"] == 0
    assert result["rule"] == "window10" and "lost reads 2" in capsys.readouterr().out
    # each rule: (left out, lost reads)
    expect = {"window5": (6, 2), "window3": (4, 1), "read-only": (3, 0), "read-or-window3": (5, 1), "session-once": (4, 1)}
    for rule, counts in expect.items():
        assert lr.main(["--repeats", "--rule", rule, "--out", str(out)]) == 0
        t = json.loads(out.read_text())["totals"]
        assert (t["suppressed"], t["lost_reads"]) == counts, rule
    # with --transcripts, the compactions are the transcripts' boundaries, not the log's PreCompact rows
    # (s1 compacted before its last recall, so b returns; s3's log row no longer counts, so e and k stay out)
    transcripts = tmp_path / "projects"
    (transcripts / "proj" / "s1").mkdir(parents=True)
    boundary = {"type": "system", "subtype": "compact_boundary", "sessionId": "s1", "timestamp": rows[3]["ts"].replace("Z", ".500Z")}
    (transcripts / "proj" / "s1.jsonl").write_text(json.dumps({"type": "user", "sessionId": "s1"}) + "\n" + json.dumps(boundary) + "\n")
    (transcripts / "proj" / "s1" / "agent.jsonl").write_text(json.dumps({**boundary, "timestamp": rows[0]["ts"]}) + "\n")   # a subagent's: ignored
    assert lr.main(["--repeats", "--rule", "session-once", "--transcripts", str(transcripts), "--out", str(out)]) == 0
    t = json.loads(out.read_text())["totals"]
    assert (t["suppressed"], t["lost_reads"]) == (5, 2)


def test_recall_names_a_page_once_per_session(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s10"); iirc.set_root(tmp_path)
    iirc.write_config_file({"max_suggested": 1})
    found = []

    def hit(*names):
        found[:] = [{"filename": f"{n}.md", "via": ["semantic"], "distance": 0.1, "summary": "s", "fm": {}} for n in names]
    monkeypatch.setattr(iirc, "hybrid_search", lambda q: [dict(r) for r in found])

    def named(*names):
        hit(*names)
        line = iirc.run_recall("why does the hook time out on a cold start?", "prompt", {})
        return [n for n in names if f"`iirc read {n}.md`" in line]
    assert named("a", "b") == ["a"]
    assert named("a", "b") == ["b"]   # a was named: its slot goes to b
    evals = [json.loads(l) for l in next((tmp_path / "st" / "dokidlc-iirc").glob("eval-*.jsonl")).read_text().splitlines()]
    assert [e["verdict"] for e in evals[-2:]] == ["repeat", "passed"]
    # another session starts clean
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s11")
    assert named("a") == ["a"]
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s10")
    for i in range(8):
        assert named(f"x{i}") == [f"x{i}"]
    assert named("a", "c") == ["c"]
    assert named("a") == []            # 10 recalls without it: a stays out
    # a page read is left out too, STORE/PAGE or bare
    iirc.log_event("read", pages=["project/d"])
    assert named("d", "e") == ["e"]
    iirc.log_event("session", trigger="SessionEnd")   # a snapshot that is not a compaction
    assert named("a", "d") == []
    # the PreCompact hook's row: the context was compacted, so a and d come back, once each
    iirc.log_event("session", trigger="PreCompact")
    assert named("a", "d") == ["a"]
    assert named("a", "d") == ["d"]
    assert named("a", "d") == []
    # the replay sweep sees no history
    hit("a")
    assert [r["verdict"] for r in iirc.recall_verdicts(iirc.hybrid_search(""), cap=1)] == ["passed"]


# p5 step 23

_REAL_REINDEX = iirc.reindex
_WORDS = ("alpha", "beta", "gamma")


@contextlib.contextmanager
def _fake_ollama(monkeypatch, model="nomic-embed-text"):
    """An ollama that answers / and /api/embed: each text's vector counts the _WORDS in it. Yields the inputs it embedded."""
    import http.server
    seen: list[str] = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"Ollama is running")

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path == "/api/embed" and body["model"] == model and body["truncate"] is True
            seen.extend(body["input"])
            vecs = [[t.count(w) + 0.0 for w in _WORDS] + [0.01] for t in body["input"]]
            out = json.dumps({"embeddings": vecs}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("OLLAMA_HOST", f"127.0.0.1:{srv.server_port}")
    iirc._RESOLVED = None
    try:
        yield seen
    finally:
        srv.shutdown()
        iirc._RESOLVED = None


def _vector_project(tmp_path, monkeypatch):
    field = _project(tmp_path, monkeypatch)
    monkeypatch.setattr(iirc, "reindex", _REAL_REINDEX)
    monkeypatch.setenv("IIRC_CACHE_DIR", str(tmp_path / "cache"))
    (field / "alpha-notes.md").write_text("---\ntitle: Alpha notes\nsummary: about alpha\n---\nalpha alpha\n")
    (field / "beta-notes.md").write_text("---\ntitle: Beta notes\nsummary: about beta\n---\nbeta\n")
    return field


def test_vector_store_round_trip(tmp_path, monkeypatch):
    import hashlib
    import numpy as np
    field = _vector_project(tmp_path, monkeypatch)
    with _fake_ollama(monkeypatch) as seen:
        iirc.reindex()
    store = iirc.STORES[0]
    path = iirc.vector_path(store)
    assert path == tmp_path / "cache" / "dokidlc-iirc" / "vectors" / store.field / "nomic-embed-text.npz"
    v = iirc.iirc_embed.load(path)
    assert list(v.names) == ["alpha-notes.md", "beta-notes.md"]           # index.md is never a page
    assert list(v.sha) == [hashlib.sha256((field / n).read_bytes()).hexdigest() for n in v.names]
    assert v.vecs.dtype == np.float32 and v.vecs.shape == (2, 4)
    assert sorted(seen) == sorted("search_document: " + (field / n).read_text() for n in v.names)
    # the page text is cut at 8,192 bytes, as memoryfield-tool cuts it
    assert iirc.iirc_embed.doc_text(b"x" * 9000) == "search_document: " + "x" * 8192
    iirc.iirc_embed.save(path, v._replace(names=v.names[:1], sha=v.sha[:1], vecs=v.vecs[:1]))
    back = iirc.iirc_embed.load(path)
    assert list(back.names) == ["alpha-notes.md"] and (back.vecs == v.vecs[:1]).all()


def test_changed_page_reembeds(tmp_path, monkeypatch):
    field = _vector_project(tmp_path, monkeypatch)
    monkeypatch.setattr(iirc, "start_background", lambda argv: None)      # the background index has its own test
    with _fake_ollama(monkeypatch) as seen:
        iirc.reindex()
        seen.clear()
        iirc.reindex()
        assert seen == []                                                  # nothing changed, nothing embedded
        (field / "beta-notes.md").write_text("---\ntitle: Beta notes\nsummary: about beta\n---\nbeta gamma gamma\n")
        (field / "alpha-notes.md").unlink()
        iirc.reindex()
        assert seen == ["search_document: " + (field / "beta-notes.md").read_text()]
        v = iirc.iirc_embed.load(iirc.vector_path(iirc.STORES[0]))
        assert list(v.names) == ["beta-notes.md"] and list(v.vecs[0][:3]) == [0.0, 2.0, 2.0]
        # a page changed since the last index is embedded before a search uses it
        (field / "gamma-notes.md").write_text("---\ntitle: Gamma notes\nsummary: about gamma\n---\ngamma\n")
        seen.clear()
        rows = iirc.hybrid_search("gamma")
        assert seen == ["search_query: gamma", "search_document: " + (field / "gamma-notes.md").read_text()] or \
            seen == ["search_document: " + (field / "gamma-notes.md").read_text(), "search_query: gamma"]
        assert "gamma-notes.md" in [r["filename"] for r in rows if "semantic" in r["via"]]
        assert "gamma-notes.md" in iirc.iirc_embed.load(iirc.vector_path(iirc.STORES[0])).names
        # more changed pages than SEARCH_REEMBED wait for the next index, so a recall stays inside the hook's limit
        for i in range(iirc.SEARCH_REEMBED + 1):
            (field / f"gamma-{i}.md").write_text(f"---\ntitle: Gamma {i}\nsummary: g\n---\ngamma\n")
        seen.clear()
        rows = iirc.hybrid_search("gamma")
        assert seen == ["search_query: gamma"]
        assert not [r for r in rows if "semantic" in r["via"] and r["filename"].startswith("gamma-") and r["filename"] != "gamma-notes.md"]


def test_search_starts_one_background_index_when_many_pages_changed(tmp_path, monkeypatch):
    """A missing store, or a pull of many pages, heals itself: the search that finds them starts `iirc index` once."""
    field = _vector_project(tmp_path, monkeypatch)
    started = []
    monkeypatch.setattr(iirc, "start_background", lambda argv: started.append(argv))
    with _fake_ollama(monkeypatch):
        iirc.reindex()
        iirc.hybrid_search("gamma")
        assert started == []                                               # nothing waiting
        for i in range(iirc.SEARCH_REEMBED + 1):
            (field / f"gamma-{i}.md").write_text(f"---\ntitle: Gamma {i}\nsummary: g\n---\ngamma\n")
        iirc.hybrid_search("gamma")
        iirc.hybrid_search("gamma")
    assert [a[-1] for a in started] == ["index"]                           # once, not on every prompt


def test_hybrid_search_in_process(tmp_path, monkeypatch):
    import math
    _vector_project(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(iirc, "tool", lambda *a, **k: calls.append(a) or pytest.fail("search never calls memoryfield-tool"))
    with _fake_ollama(monkeypatch) as seen:
        iirc.reindex()
        seen.clear()
        rows = iirc.hybrid_search("alpha")
        assert seen == ["search_query: alpha"]
        semantic = [r for r in rows if "semantic" in r["via"]]
        # beta-notes is at distance near 1, past the 0.45 the tool returned at most
        assert [r["filename"] for r in semantic] == ["alpha-notes.md"]
        q, p = [1, 0, 0, 0.01], [3, 0, 0, 0.01]                                # "alpha" once; the page says it three times
        cos = sum(a * b for a, b in zip(q, p)) / math.sqrt(sum(a * a for a in q) * sum(b * b for b in p))
        r = semantic[0]
        assert abs(r["distance"] - (1 - cos)) < 1e-6 and r["store"] == "project" and r["summary"] == "about alpha"
        assert iirc.tool_env()["OLLAMA_HOST"] == iirc.NO_EMBEDDING_HOST    # the tool's own reindex never reaches the host
    assert calls == []


# p5 step 24

def _machine_model(model):
    """The setup file names this embedding model, as `iirc setup` writes it."""
    path = iirc.config_file(); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'embedding = {{backend = "{iirc.iirc_embed.MODELS[model].backend}", model = "{model}"}}\n')
    iirc._CONFIG = None


def test_knobs_per_model(tmp_path, monkeypatch, capsys):
    """Each model has a [recall.MODEL-ID] table with its own defaults and ranges; only the active model's table is checked."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    toml = tmp_path / ".claude" / "iirc.toml"; toml.parent.mkdir()
    toml.write_text('[recall.nomic-embed-text]\nsemantic_only = 0.3\n\n[recall."qwen3-embedding-0.6b"]\nsemantic_only = 0.5\nboth = 0.7\n\n'
                    '[recall.all-minilm-l6-v2]\nboth = 0.95\n')
    iirc.set_root(tmp_path)   # no embedding in the setup file: nomic-embed-text
    assert iirc.CONFIG_ERROR is None and iirc.RECALL == {"semantic_only": 0.3, "both": 0.38}   # minilm's 0.95 is not checked
    _machine_model("qwen3-embedding:0.6b")
    iirc.set_root(tmp_path)
    assert iirc.CONFIG_ERROR is None and iirc.RECALL == {"semantic_only": 0.5, "both": 0.7}    # past nomic's 0.60, inside qwen3's range
    iirc.main(["knobs"])
    assert '[recall."qwen3-embedding-0.6b"]' in capsys.readouterr().out
    iirc.main(["knobs", "set", "both", "0.8"])
    assert 'semantic_only = 0.5\nboth = 0.8\n' in toml.read_text() and "[recall.nomic-embed-text]\nsemantic_only = 0.3\n" in toml.read_text()
    _machine_model("all-minilm-l6-v2")
    iirc.set_root(tmp_path)
    assert "[recall.all-minilm-l6-v2] both must be a number from 0.1 to 0.9" in iirc.CONFIG_ERROR
    toml.write_text("[recall.nomic-embed-text]\nboth = 0.4\n")
    iirc.set_root(tmp_path)
    assert iirc.CONFIG_ERROR is None and iirc.RECALL == {"semantic_only": 0.6, "both": 0.68}   # minilm's own defaults
    grid = iirc.knob_grid()
    assert min(k["semantic_only"] for k in grid) == 0.1 and max(k["both"] for k in grid) == 0.9 and all(k["both"] >= k["semantic_only"] for k in grid)
    iirc.main(["knobs", "set", "semantic_only", "0.55"])   # a new table for the active model, after the others
    assert toml.read_text() == "[recall.nomic-embed-text]\nboth = 0.4\n\n[recall.all-minilm-l6-v2]\nsemantic_only = 0.55\n"
    toml.write_text("[recall.nomic]\nboth = 0.4\n")
    iirc.set_root(tmp_path)
    assert "[recall.nomic] names no embedding model" in iirc.CONFIG_ERROR and "nomic-embed-text" in iirc.CONFIG_ERROR
    toml.unlink(); iirc.set_root(tmp_path)


def test_flat_recall_moves_on_doctor_fix(tmp_path, monkeypatch, capsys):
    """A flat [recall] key fails with the fix named; doctor --fix moves it into nomic's table, where every flat knob was measured."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    toml = tmp_path / ".claude" / "iirc.toml"; toml.parent.mkdir()
    toml.write_text("ui = true\n\n[recall]  # the gate\nsemantic_only = 0.3   # measured\nboth = 0.9\n")
    iirc.set_root(tmp_path)
    assert "`iirc doctor --fix`" in iirc.CONFIG_ERROR and "[recall.nomic-embed-text]" in iirc.CONFIG_ERROR
    assert iirc.knob_error_only()
    iirc.main(["doctor", "--health"])   # the /iirc card still gets its JSON
    assert set(json.loads(capsys.readouterr().out)) == {"suspect", "stores"}
    iirc.main(["doctor", "--brief"])
    assert "hooks off" in (out := capsys.readouterr().out) and "`iirc doctor --fix`" in out
    monkeypatch.setattr(iirc, "install_tool", lambda pin: False)   # stop before the network checks
    monkeypatch.setattr(iirc.shutil, "which", lambda name: None)
    with pytest.raises(SystemExit):
        iirc.main(["doctor", "--fix"])
    out = capsys.readouterr().out
    assert "moved [recall] to [recall.nomic-embed-text]" in out and "commented out `both = 0.9`" in out and "ok  .claude/iirc.toml loads" in out
    assert toml.read_text() == ("ui = true\n\n[recall.nomic-embed-text]  # the gate\nsemantic_only = 0.3   # measured\n"
                                "# both = 0.9  # iirc doctor --fix: must be a number from 0.1 to 0.6\n")
    iirc.set_root(tmp_path)
    assert iirc.CONFIG_ERROR is None and iirc.RECALL == {"semantic_only": 0.3, "both": 0.38}
    # beside an existing nomic table, each flat key moves on its own, and the table's own value stays
    toml.write_text("[recall]\nsemantic_only = 0.26\nboth = 0.4\n\n[recall.nomic-embed-text]\nsemantic_only = 0.3\n")
    iirc.set_root(tmp_path)
    assert iirc.knob_error_only()
    with pytest.raises(SystemExit):
        iirc.main(["doctor", "--fix"])
    iirc.set_root(tmp_path)
    assert iirc.CONFIG_ERROR is None and iirc.RECALL == {"semantic_only": 0.3, "both": 0.4}
    assert "# semantic_only = 0.26  # iirc doctor --fix: [recall.nomic-embed-text] has its own" in toml.read_text()
    toml.unlink(); iirc.set_root(tmp_path)


# p5 step 25

@contextlib.contextmanager
def _fake_openai(monkeypatch, model):
    """An OpenAI-compatible host: 404 on GET, and /v1/embeddings with _fake_ollama's vectors, listed in reverse order. Yields the inputs."""
    import http.server
    seen: list[str] = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(404); self.end_headers()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path == "/v1/embeddings" and set(body) == {"model", "input"} and body["model"] == model
            seen.extend(body["input"])
            data = [{"index": i, "embedding": [t.count(w) + 0.0 for w in _WORDS] + [0.01]} for i, t in enumerate(body["input"])]
            out = json.dumps({"data": data[::-1], "model": model}).encode()
            self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers(); self.wfile.write(out)

        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    iirc.write_config_file({"semantic": True, "embedding": {"backend": "openai", "model": model, "url": f"http://127.0.0.1:{srv.server_port}/v1"}})
    iirc._RESOLVED = None
    try:
        yield seen
    finally:
        srv.shutdown()
        iirc._RESOLVED = None


@pytest.mark.parametrize("model", ["nomic-embed-text", "qwen3-embedding:0.6b", "embeddinggemma", "qwen3-embedding"])
def test_backend_prefixes(tmp_path, monkeypatch, capsys, model):
    """Each model gets its own query and document prefixes over the raw page file, through its own backend, into its own store."""
    field = _vector_project(tmp_path, monkeypatch)
    m = iirc.iirc_embed.MODELS[model]
    if m.backend == "ollama":
        iirc.write_config_file({"semantic": True, "embedding": {"backend": "ollama", "model": model}})
        server = _fake_ollama(monkeypatch, model)
    else:
        server = _fake_openai(monkeypatch, model)
    with server as seen:
        assert iirc.active_model() == m
        iirc.reindex()
        assert sorted(seen) == sorted(m.doc_prefix + (field / n).read_text() for n in ("alpha-notes.md", "beta-notes.md"))
        path = iirc.vector_path(iirc.STORES[0])
        assert path.name == iirc.iirc_embed.table_name(model) + ".npz" and iirc.iirc_embed.load(path).names == ["alpha-notes.md", "beta-notes.md"]
        seen.clear()
        rows = iirc.hybrid_search("alpha")
        assert seen == [m.query_prefix + "alpha"]
        assert [r["filename"] for r in rows if "semantic" in r["via"]] == ["alpha-notes.md"]
    if m.backend == "openai":
        # a hosted endpoint that does not answer is a dead host: string search, and the brief says so
        s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
        iirc.write_config_file({"semantic": True, "embedding": {"backend": "openai", "model": model, "url": f"http://127.0.0.1:{port}"}})
        iirc._RESOLVED = None
        assert iirc.semantic_search("alpha") == []
        capsys.readouterr()
        iirc.main(["doctor", "--brief"])
        assert f"string only (127.0.0.1:{port} does not answer" in capsys.readouterr().out
        iirc._RESOLVED = None
    assert iirc.iirc_embed.MODELS["qwen3-embedding:0.6b"].query_prefix == \
        "Instruct: Given a request to a coding agent, retrieve the memory pages that help with it\nQuery: "
    assert (iirc.iirc_embed.MODELS["embeddinggemma"].query_prefix, iirc.iirc_embed.MODELS["embeddinggemma"].doc_prefix) == \
        ("task: search result | query: ", "title: none | text: ")


def _load_cpu():
    loader = SourceFileLoader("iirc_cpu", str(ROOT / "bin" / "iirc-cpu"))
    spec = importlib.util.spec_from_loader("iirc_cpu", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class _StubTokenizer:
    """Whitespace tokens with character offsets; a token's id is 1 + its index in _WORDS, else 4."""
    def __init__(self):
        self.truncate, self.pad = None, False
    def no_truncation(self): self.truncate = None
    def no_padding(self): self.pad = False
    def enable_truncation(self, n): self.truncate = n
    def enable_padding(self): self.pad = True

    def encode(self, text, add_special_tokens=True):
        import types
        offsets = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)][:self.truncate]
        ids = [(_WORDS.index(text[a:b]) + 1) if text[a:b] in _WORDS else 4 for a, b in offsets]
        return types.SimpleNamespace(offsets=offsets, ids=ids, attention_mask=[1] * len(ids))

    def encode_batch(self, texts):
        out = [self.encode(t) for t in texts]
        width = max(len(e.ids) for e in out)
        for e in out:
            e.ids += [0] * (width - len(e.ids)); e.attention_mask += [0] * (width - len(e.attention_mask))
        return out


class _StubSession:
    """A token's hidden state is the one-hot of its id, so a mean-pooled window counts its _WORDS. Records each batch."""
    def __init__(self):
        self.batches = []

    def run(self, outputs, feeds):
        import numpy as np
        ids = feeds["input_ids"]
        assert set(feeds) == {"input_ids", "attention_mask", "token_type_ids"} and ids.dtype == np.int64
        self.batches.append(ids.shape)
        return [np.eye(5, dtype=np.float32)[ids]]


def test_onnx_windows_score_best_window(tmp_path, monkeypatch):
    import numpy as np
    cpu = _load_cpu()
    tok, sess = _StubTokenizer(), _StubSession()
    text = " ".join(["alpha"] * 160 + ["beta"] * 140 + ["gamma"] * 150)   # 450 tokens
    wins = cpu.windows(text, tok)
    assert [len(w.split()) for w in wins] == [200, 200, 150]               # windows of 200 at a stride of 150; the last one ends the text
    assert wins[0].startswith("alpha") and wins[2] == " ".join(["beta"] * 0 + ["gamma"] * 150)
    assert cpu.windows("", tok) == [""] and cpu.windows("one two", tok) == ["one two"]
    vecs, owner = cpu.embed_texts([text, "beta beta"], "doc", tok, sess)
    assert list(owner) == [0, 0, 0, 1] and vecs.shape == (4, 5) and np.allclose(np.linalg.norm(vecs, axis=1), 1)
    qv, qo = cpu.embed_texts(["gamma " * 300], "query", tok, sess)            # a query is one window, cut at 256 tokens
    assert list(qo) == [0] and sess.batches[-1] == (1, 256)
    # bin/iirc: the onnx backend sends the plain page text and keeps each page's best window
    field = _vector_project(tmp_path, monkeypatch)
    (field / "long-notes.md").write_text(f"---\ntitle: Long notes\nsummary: mostly alpha\ntopics:\n- greek\nkind: finding\n---\n{text}\n\n## Sources\n- gamma gamma\n")
    iirc.write_config_file({"semantic": True, "embedding": {"backend": "onnx", "model": "all-minilm-l6-v2"}})
    sent = []

    def run_cpu(backend, texts, kind):
        sent.append((kind, texts))
        return cpu.embed_texts(texts, kind, tok, sess)
    monkeypatch.setattr(iirc.iirc_embed, "run_cpu", run_cpu)
    monkeypatch.setattr(iirc, "cpu_ready", lambda: True)
    iirc._RESOLVED = None
    iirc.reindex()
    docs = dict(zip(sorted(p.name for p in iirc.list_pages(field)), sent[0][1]))
    assert docs["long-notes.md"] == f"Long notes\nmostly alpha\nTopics: greek\n\n{text}\n"   # no YAML, no Sources
    v = iirc.iirc_embed.load(iirc.vector_path(iirc.STORES[0]))
    assert v.vecs.shape[1] == 5 and list(v.owner).count(v.names.index("long-notes.md")) == 3
    rows = {r["filename"]: r["distance"] for r in iirc.semantic_search("gamma")}
    wv, _ = cpu.embed_texts([docs["long-notes.md"]], "doc", tok, sess)
    qv, _ = cpu.embed_texts(["gamma"], "query", tok, sess)
    best, mean = 1 - float((wv @ qv[0]).max()), 1 - float(wv.mean(axis=0) @ qv[0] / np.linalg.norm(wv.mean(axis=0)))
    assert abs(rows["long-notes.md"] - best) < 1e-6 and best < 0.01 < mean   # its last window is nearly all gamma
    assert sent[-1] == ("query", ["gamma"])
    assert "long-notes.md" in [label for label, _, _ in iirc.index_rows()]  # one vector per page for near-duplicates
    iirc._RESOLVED = None


def test_setup_offers_models(tmp_path, monkeypatch, capsys):
    import hashlib
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(iirc, "host_answers", lambda base, timeout=2.0, fresh=False, any_status=False: False)
    monkeypatch.setattr(iirc.sys.stdin, "isatty", lambda: True)
    answers = iter(["1", "1"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    iirc.main(["setup"])
    menu = capsys.readouterr().out
    for offer in ("ollama on this machine", "a remote ollama host", "OpenAI-compatible", "this CPU", "all-minilm-l6-v2", "string search",
                  "nomic-embed-text", "qwen3-embedding:0.6b", "embeddinggemma"):
        assert offer in menu
    assert iirc.read_config() == {"semantic": True, "embedding_host": "http://127.0.0.1:11434",
                                  "embedding": {"backend": "ollama", "model": "qwen3-embedding:0.6b"}}
    iirc.main(["setup", "--openai", "https://llm.example.net/v1/"])
    assert iirc.read_config()["embedding"] == {"backend": "openai", "model": "qwen3-embedding", "url": "https://llm.example.net"}
    iirc.main(["setup", "--host", "frame:11434", "--model", "embeddinggemma"])
    assert iirc.read_config()["embedding"] == {"backend": "ollama", "model": "embeddinggemma"} and iirc.active_model().id == "embeddinggemma"
    with pytest.raises(SystemExit):
        iirc.main(["setup", "--local", "--model", "all-minilm-l6-v2"])   # not an ollama model
    # the CPU tier fetches its files at the pinned commit, checks each sha256, and runs bin/iirc-cpu once
    fetched, checked = [], []
    blobs = {"onnx/model.onnx": b"model bytes", "tokenizer.json": b"{}"}
    monkeypatch.setattr(iirc.iirc_embed, "MINILM_FILES", {name: (src, hashlib.sha256(blobs[src]).hexdigest())
                                                          for name, (src, _) in iirc.iirc_embed.MINILM_FILES.items()})
    monkeypatch.setattr(iirc, "fetch_url", lambda url, dest: fetched.append(url) or dest.write_bytes(blobs[url.split(f"/{iirc.iirc_embed.MINILM_COMMIT}/")[1]]))
    monkeypatch.setattr(iirc, "cpu_check", lambda: checked.append(1) or (True, ""))
    iirc.main(["setup", "--cpu"])
    assert iirc.read_config()["embedding"] == {"backend": "onnx", "model": "all-minilm-l6-v2"} and checked == [1]
    assert all(u.startswith(f"https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/{iirc.iirc_embed.MINILM_COMMIT}/") for u in fetched)
    assert len(fetched) == 2 and iirc.cpu_ready()
    iirc.main(["setup", "--cpu"])
    assert len(fetched) == 2                                               # files whose sha matches are not fetched again
    (iirc.minilm_dir() / "tokenizer.json").write_bytes(b"tampered")
    blobs["tokenizer.json"] = b"tampered too"
    iirc.write_config_file({"semantic": False})
    with pytest.raises(SystemExit):
        iirc.main(["setup", "--cpu"])                                      # a file that fails its sha256 is refused
    assert "sha256" in capsys.readouterr().err and iirc.read_config() == {"semantic": False}
    assert iirc.iirc_embed.MINILM_COMMIT == "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"


# p5 step 13

def test_line_replay_two_pages(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    lr = _line_replay()
    monkeypatch.setattr(lr, "iirc", lambda: iirc)
    rows = [{"page": f"p{i}.md", "store": "project", "summary": f"page {i}", "distance": 0.2, "rule": "meaning"} for i in range(3)]
    assert lr.current(rows).count("`iirc read ") == 3
    line = lr.twopages(rows)
    assert line.count("`iirc read ") == 2 and line.startswith("iirc: 2 pages may apply.") and "p2" not in line


def test_line_replay_followup_query(tmp_path, monkeypatch):
    lr = _line_replay()
    monkeypatch.setattr(lr, "iirc", lambda: iirc)
    short, long = "nice. Lets commit and push what we have.", "x" * 80
    assert lr.followup_query(short, "add the replay variants") == "add the replay variants " + short
    assert lr.followup_query(long, "add the replay variants") == long
    assert lr.followup_query(short, None) == short
    # the previous human prompt comes from the session's transcript, capped as the prompts file keeps it
    session = "abcd1234-0000-0000-0000-000000000000"
    project = tmp_path / "projects" / "-repo"
    project.mkdir(parents=True)

    def user(text, ts):
        return json.dumps({"type": "user", "timestamp": ts, "message": {"content": text}})
    (project / f"{session}.jsonl").write_text("\n".join([
        user("y" * 400, "2026-10-09T10:00:00Z"),
        user("<task-notification>done</task-notification>", "2026-10-09T10:01:00Z"),
        user(short, "2026-10-09T10:02:00Z"),
    ]) + "\n")
    p = {"repo": "/repo", "qid": "abcd1234/key", "prompt": short}
    assert lr.previous_prompt(p, tmp_path / "projects") == "y" * 300
    assert lr.previous_prompt({**p, "qid": "ffff0000/key"}, tmp_path / "projects") is None


# p5 step 26
def test_replay_files_pool_lists_unlabelled(tmp_path, monkeypatch):
    rf = _replay_files()
    replay = [{"repo": "/r", "qid": "q1", "prompt": "one", "via": "prompt", "page": "a.md", "label": "relevant"},
              {"repo": "/r", "qid": "q1", "prompt": "one", "via": "prompt", "page": "project/b.md", "label": "noise"},
              {"repo": "/r", "qid": "q2", "prompt": "two", "via": "prompt", "page": "c.md", "label": "unsure"}]
    ranked = {"m1": {"q1": ["a.md", "b.md", "c.md", "d.md"], "q2": ["c.md", "e.md"]},
              "m2": {"q1": ["d.md", "c.md", "a.md"], "q2": []}}
    assert rf.pool_rows("ab", replay, ranked) == [
        {"set": "ab", "qid": "q1", "page": "c.md", "models": ["m1", "m2"]},
        {"set": "ab", "qid": "q1", "page": "d.md", "models": ["m2"]},     # m1 ranks it fourth, past the pool's depth
        {"set": "ab", "qid": "q2", "page": "e.md", "models": ["m1"]},     # an unsure label is a label
    ]
    # each model searches through a machine config of its own, in temporary directories, after a full index
    field = _vector_project(tmp_path, monkeypatch)
    before = {k: os.environ.get(k) for k in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "IIRC_CACHE_DIR")}
    seen = []

    def embed(backend, texts, kind="doc", timeout=None):
        import numpy as np
        assert rf.iirc.read_config()["embedding"]["model"] == backend.model.id
        seen.append((backend.model.id, str(rf.iirc.config_file()), os.environ["IIRC_CACHE_DIR"]))
        near = 0 if backend.model.id == "nomic-embed-text" else 1     # "gamma" is near alpha for nomic, near beta for gemma
        return [np.asarray([[t.count("alpha") + (near == 0) * t.count("gamma"), t.count("beta") + (near == 1) * t.count("gamma"), 0.01]],
                           dtype=np.float32) for t in texts]
    monkeypatch.setattr(iirc.iirc_embed, "embed", embed)
    monkeypatch.setattr(rf.iirc, "start_background", lambda argv: 1 / 0)
    monkeypatch.setattr(rf.iirc, "resolve_host", lambda: ("http://127.0.0.1:9", "default", True))    # the stub is the backend; CI has no ollama
    prompts = {"q1": ("gamma rays", "prompt")}
    assert rf.ranked_pages("nomic-embed-text", tmp_path, prompts, tmp_path / "pool") == {"q1": ["alpha-notes.md"]}
    assert rf.ranked_pages("embeddinggemma", tmp_path, prompts, tmp_path / "pool") == {"q1": ["beta-notes.md"]}
    assert {m for m, _, _ in seen} == {"nomic-embed-text", "embeddinggemma"}
    assert all(cfg.startswith(str(tmp_path / "pool")) and cache.startswith(str(tmp_path / "pool")) for _, cfg, cache in seen)
    assert {k: os.environ.get(k) for k in before} == before
    assert (field / "index.md").read_text() == iirc.INDEX_TEMPLATE                   # no index stamp, no commit in the repository


def test_replay_files_merge_pool(tmp_path, capsys):
    rf = _replay_files()
    row = {"repo": "/r", "qid": "q1", "prompt": "one", "via": "prompt", "page": "a.md", "label": "relevant"}
    (tmp_path / "replay-ab.jsonl").write_text(json.dumps(row) + "\n")
    labels = [{"set": "ab", "qid": "q1", "page": "b.md", "label": "noise", "note": "other mechanism"},
              {"set": "ab", "qid": "q1", "page": "project/a.md", "label": "noise", "note": "already labelled"},
              {"set": "ab", "qid": "q9", "page": "c.md", "label": "relevant", "note": "no such prompt"}]
    (tmp_path / "pool-round-2.jsonl").write_text("".join(json.dumps(x) + "\n" for x in labels))
    rf.merge(tmp_path)
    rf.merge(tmp_path)                                                  # a second merge adds nothing
    rows = [json.loads(x) for x in (tmp_path / "replay-ab.jsonl").read_text().splitlines()]
    assert rows == [row, {**row, "page": "b.md", "label": "noise"}]
    assert "1 pool labels added, 2 skipped" in capsys.readouterr().out


def test_setup_default_order(tmp_path, monkeypatch, capsys):
    """qwen3-embedding:0.6b where ollama or the machine's host answers, all-minilm-l6-v2 otherwise, string search last."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(iirc.sys.stdin, "isatty", lambda: True)
    answers, asked = [], []
    monkeypatch.setattr("builtins.input", lambda prompt="": asked.append(prompt) or answers.pop(0))
    monkeypatch.setattr(iirc, "model_present", lambda host, model, timeout=2.0: True)
    up = {"http://127.0.0.1:11434"}
    monkeypatch.setattr(iirc, "host_answers", lambda base, timeout=2.0, fresh=False, any_status=False: base in up)
    answers[:] = ["", ""]                                                   # Enter, Enter: ollama here, its first model
    iirc.main(["setup"])
    out = capsys.readouterr().out
    assert iirc.read_config()["embedding"] == {"backend": "ollama", "model": "qwen3-embedding:0.6b"}
    assert asked[0].endswith("[1]: ") and out.index("1. qwen3-embedding:0.6b") < out.index("nomic-embed-text")
    menu = [line for line in out.splitlines() if re.match(r"\s+\d\. ", line)]
    assert "string search" in menu[len(iirc.SETUP_MENU.splitlines()) - 2]   # the last choice of the menu
    iirc.main(["setup", "--local"])
    assert iirc.read_config()["embedding"]["model"] == "qwen3-embedding:0.6b"
    # the machine's own ollama host answers and this one does not: Enter takes that host
    up.clear(); up.add("http://frame:11434")
    iirc.write_config_file({"embedding_host": "http://frame:11434"})
    answers[:] = ["", "", ""]; asked.clear()
    iirc.main(["setup"])
    assert asked[0].endswith("[2]: ") and iirc.read_config()["embedding_host"] == "http://frame:11434"
    assert iirc.read_config()["embedding"]["model"] == "qwen3-embedding:0.6b"
    # nothing answers: Enter takes this CPU
    up.clear()
    monkeypatch.setattr(iirc, "fetch_minilm", lambda: None)
    monkeypatch.setattr(iirc, "cpu_check", lambda: (True, ""))
    answers[:] = [""]; asked.clear()
    iirc.main(["setup"])
    assert asked[0].endswith("[4]: ") and iirc.read_config()["embedding"] == {"backend": "onnx", "model": "all-minilm-l6-v2"}


def test_near_duplicate_thresholds_per_model(tmp_path, monkeypatch):
    """Page-to-page distances differ by model as prompt-to-page ones do; a pair close for one model is not close for another."""
    import numpy as np
    nomic, gemma = iirc.iirc_embed.MODELS["nomic-embed-text"], iirc.iirc_embed.MODELS["embeddinggemma"]
    assert nomic.near == (0.10, 0.07)
    for m in iirc.iirc_embed.MODELS.values():
        assert 0 < m.near[1] < m.near[0] < m.cut
    _project(tmp_path, monkeypatch)
    monkeypatch.setattr(iirc, "cache_dir", lambda: tmp_path / "cache")
    d = (nomic.near[0] + gemma.near[0]) / 2                     # past nomic's line, inside gemma's
    vecs = {"a.md": (1.0, 0.0), "b.md": (1 - d, (1 - (1 - d) ** 2) ** 0.5)}
    rows = np.zeros((2, 768), dtype=np.float32)
    for i, head in enumerate(vecs.values()):
        rows[i, :2] = head
    for model in (nomic.id, gemma.id):
        path = iirc.iirc_embed.store_path(tmp_path / "cache", iirc.field_name(tmp_path), model)
        iirc.iirc_embed.save(path, iirc.iirc_embed.Vectors(list(vecs), ["sha-a", "sha-b"], rows))
    assert iirc.near_duplicates() == []                          # nomic
    iirc.write_config_file({"embedding": {"backend": "ollama", "model": gemma.id}})
    assert iirc.near_duplicates() == [(round(d, 3), "a.md", "b.md")]   # same page shas, other model: not nomic's cached answer


# p5 step 27


def test_docs_name_every_command():
    """USAGE.md names every top-level iirc command as a command, and the flags this quest added."""
    usage = (ROOT / "docs" / "USAGE.md").read_text()
    commands = re.findall(r'\bsub\.add_parser\(\s*"([a-z-]+)"', (ROOT / "bin" / "iirc").read_text())
    assert len(commands) > 20
    # as a command, in backticks: the noun "recall" or "read" in prose does not count
    missing = [c for c in commands if not re.search(rf"`(?:/?iirc )?{re.escape(c)}\b", usage)]
    assert missing == []
    assert "`iirc audit" in usage and "--replay" in usage


def test_audit_names_the_active_model(tmp_path, monkeypatch, capsys):
    """The audit's last line names the model its vectors came from, not the pin's nomic."""
    vectors = _audit_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(iirc, "page_vectors", lambda: vectors)
    iirc.write_config_file({"embedding": {"backend": "ollama", "model": "qwen3-embedding:0.6b"}})
    iirc.main(["audit", "old.md"])
    assert capsys.readouterr().out.splitlines()[-1] == "1 finding in 1 page; vectors checked with qwen3-embedding:0.6b"


# p5 review fixes, R3


def test_failure_recall_saves_redacted_text(tmp_path, monkeypatch):
    """A token in a failed command or its error never reaches the prompts file."""
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "f1")
    (tmp_path / ".iirc").mkdir(); iirc.set_root(tmp_path)
    monkeypatch.setattr(iirc, "hybrid_search", lambda q: [])
    token = "ghp_" + "A1b2C3d4E5" * 4
    command = f'curl -fsS -H "Authorization: Bearer {token}" https://api.github.com/user'
    error = f"Exit code 22\ncurl: (22) The requested URL returned error: 401 for {token}"
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "error": error})))
    iirc.main(["recall", "--failure"])
    kept = (tmp_path / "st" / "dokidlc-iirc" / "prompts" / "f1.jsonl").read_text()
    assert "[REDACTED]" in kept
    assert token not in kept


def test_failed_recall_is_not_logged_as_timeout(tmp_path, monkeypatch):
    """A recall that raises removes its inflight marker, so the next recall logs no timeout."""
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "e1")
    (tmp_path / ".iirc").mkdir(); iirc.set_root(tmp_path)
    prompt = json.dumps({"prompt": "why does uv tool install memoryfield-tool fail with pysqlite3-binary"})

    def broken(q):
        raise ValueError("shapes (1,768) and (1024,) not aligned")
    monkeypatch.setattr(iirc, "hybrid_search", broken)
    monkeypatch.setattr("sys.stdin", io.StringIO(prompt))
    iirc.main(["recall"])
    monkeypatch.setattr(iirc, "hybrid_search", lambda q: [])
    monkeypatch.setattr("sys.stdin", io.StringIO(prompt))
    iirc.main(["recall"])
    assert [r["cmd"] for r in iirc.read_log()] == ["recall"]


def test_line_pages_counted_from_its_pages(tmp_path, monkeypatch):
    """A summary that holds "`iirc read x.md`" does not count as a page the line names."""
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "c1")
    (tmp_path / ".iirc").mkdir(); iirc.set_root(tmp_path)
    fm = {"title": "t", "summary": "s", "kind": "finding"}
    rows = [{"filename": f"{n}.md", "store": "project", "via": ["pysqlite3"], "distance": None, "rare_terms": ["pysqlite3"], "head_terms": [],
             "summary": summary, "fm": fm} for n, summary in (("a", "run `iirc read x.md` first"), ("b", "the uv override"))]
    monkeypatch.setattr(iirc, "hybrid_search", lambda q: rows)
    one = len(iirc.recall_line(rows[:1]).encode())
    monkeypatch.setattr(iirc, "recall_max_bytes", lambda: one + 10)   # room for a only
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": "why does uv tool install memoryfield-tool fail with pysqlite3-binary"})))
    iirc.main(["recall"])
    assert iirc.read_log()[0]["pages"] == ["a.md"]
    evals = [json.loads(line) for f in (tmp_path / "st" / "dokidlc-iirc").glob("eval-*.jsonl") for line in f.read_text().splitlines()]
    assert {e["page"]: e["verdict"] for e in evals} == {"a.md": "passed", "b.md": "line_cut"}


def test_subagent_recall_keeps_its_own_repeat_history(tmp_path, monkeypatch):
    """A subagent's hooks carry agent_id: a page the parent's line named is new to the subagent, and a page its own line named is a repeat."""
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    (tmp_path / ".iirc").mkdir(); iirc.set_root(tmp_path)
    row = {"filename": "a.md", "store": "project", "via": ["semantic", "pysqlite3"], "distance": 0.2, "rare_terms": ["pysqlite3"], "head_terms": [],
           "summary": "the uv override", "fm": {"title": "t", "summary": "s", "kind": "finding"}}
    monkeypatch.setattr(iirc, "hybrid_search", lambda q: [dict(row)])
    prompt = {"session_id": "s1", "prompt": "why does uv tool install memoryfield-tool fail with pysqlite3-binary"}
    failure = {"session_id": "s1", "agent_id": "ag1", "agent_type": "general-purpose", "tool_name": "Bash",
               "tool_input": {"command": "uv tool install memoryfield-tool"}, "error": "Exit code 1\nno wheels for pysqlite3-binary"}
    for event, flag in ((prompt, []), (failure, ["--failure"]), (failure, ["--failure"]), (prompt, [])):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(event)))
        iirc.main(["recall", *flag])
    recalls = [(r.get("agent"), r["pages"]) for r in iirc.read_log() if r["cmd"] == "recall"]
    assert recalls == [(None, ["a.md"]), ("ag1", ["a.md"]), ("ag1", []), (None, [])]
