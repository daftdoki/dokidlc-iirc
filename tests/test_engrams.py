"""Tests for scripts/engrams that need neither the tool nor ollama."""

import json
import re
import socket
import threading
import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_loader = SourceFileLoader("engrams", str(ROOT / "bin" / "engrams"))
_spec = importlib.util.spec_from_loader("engrams", _loader)
engrams = importlib.util.module_from_spec(_spec)
_loader.exec_module(engrams)


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
    assert engrams.field_name(a) == engrams.field_name(a)
    assert engrams.field_name(a) != engrams.field_name(b)
    assert engrams.NAME_RE.match(engrams.field_name(a))
    assert engrams.field_name(a).startswith("agent-one-")
    assert engrams.config_path(a) != engrams.config_path(b)   # two clones, two configs


def test_config_text_points_at_dot_memory(tmp_path):
    text = engrams.config_text(tmp_path)
    assert f'location = "{(tmp_path / ".engrams").resolve()}"' in text
    assert 'index_location = "cache"' in text
    assert f"[memoryfields.{engrams.field_name(tmp_path)}]" in text


def test_normalize_host():
    assert engrams.normalize_host(None) == "http://127.0.0.1:11434"
    assert engrams.normalize_host("localhost:11434") == "http://localhost:11434"
    assert engrams.normalize_host("http://x:1/") == "http://x:1"
    assert engrams.normalize_host("https://x:1") == "https://x:1"


def test_host_guard_closed_port_returns_fast():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    assert engrams.host_answers(f"http://127.0.0.1:{port}", timeout=1.0) is False


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
    assert engrams.host_answers(f"http://127.0.0.1:{port}", timeout=1.0) is False
    assert time.monotonic() - start < 3.0
    stop.set(); t.join(); srv.close()


def test_read_pin(tmp_path):
    p = tmp_path / "pin"
    p.write_text("# comment\ntool_rev=abc123\nmodel = nomic-embed-text\n\n")
    assert engrams.read_pin(p) == {"tool_rev": "abc123", "model": "nomic-embed-text"}


def test_pin_matches_prefix_either_way():
    pin = {"tool_rev": "3e447e1d5c4840028cce3c05e70e7349923fc634"}
    assert engrams.pin_matches(pin, "3e447e1d5c4840028cce3c05e70e7349923fc634")
    assert engrams.pin_matches(pin, "3e447e1")
    assert not engrams.pin_matches(pin, "deadbeef")
    assert not engrams.pin_matches(pin, None)


def test_filter_results_drops_index_md():
    rows = [{"filename": "index.md"}, {"filename": "a.md"}]
    assert engrams.filter_results(rows) == [{"filename": "a.md"}]


def test_tokens_estimate():
    assert engrams.tokens(0) == 0
    assert engrams.tokens(4) == 1
    assert engrams.tokens(5) == 2


def test_strip_ansi():
    assert engrams.strip_ansi("\x1b[36m/a/b\x1b[39m\n") == "/a/b\n"


def test_parse_and_render_round_trip():
    text = "---\ntitle: T\nsummary: S\ntopics:\n- a\nkind: finding\ncreated: '2026-09-01T00:00:00Z'\n---\nbody\n\n## Sources\n\n- x\n"
    fm, body = engrams.parse_page(text)
    assert fm["topics"] == ["a"] and fm["created"] == "2026-09-01T00:00:00Z"
    out = engrams.render_page(fm, body)
    assert "created: '2026-09-01T00:00:00Z'" in out
    assert out.endswith("- x\n")
    assert engrams.parse_page(out) == (fm, body)


def test_parse_page_without_frontmatter():
    assert engrams.parse_page("just text\n") == ({}, "just text\n")


def test_validate_page_rules():
    good = {"title": "T", "summary": "S", "topics": ["a"], "kind": "finding"}
    assert engrams.validate_page("ok-page.md", good, "b\n\n## Sources\n\n- x\n") == []
    errs = engrams.validate_page("Bad_Name.md", {"title": "T"}, "no sources")
    assert any("page name" in e for e in errs)
    assert any("summary" in e for e in errs)
    assert any("topics" in e for e in errs)
    assert any("kind" in e for e in errs)
    assert any("Sources" in e and not e.startswith("warning:") for e in errs)   # an error, not a warning
    assert engrams.validate_page("ok-page.md", good, "b\n\n## sources\n\n- x\n") == []
    assert any("index.md" in e for e in engrams.validate_page("index.md", good, "## Sources\n"))


def test_fill_ref_from_git(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "t"], check=True)
    (tmp_path / "docs").mkdir(); (tmp_path / "docs" / "a.md").write_text("one\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "one"], check=True)
    sha = subprocess.run(["git", "-C", str(tmp_path), "log", "-1", "--format=%h"], capture_output=True, text=True).stdout.strip()
    assert engrams.fill_ref("docs/a.md", tmp_path) == f"docs/a.md@{sha}"
    assert engrams.fill_ref("docs/a.md@abc1234", tmp_path) == "docs/a.md@abc1234"
    with pytest.raises(SystemExit):
        engrams.fill_ref("docs/missing.md", tmp_path)
    with pytest.raises(SystemExit):
        engrams.fill_ref("docs/a.md@nothex", tmp_path)


def test_regenerate_index_counts_topics_and_keeps_head(tmp_path):
    field = tmp_path / ".engrams"; field.mkdir()
    (field / "index.md").write_text("---\ntitle: Engrams\n---\n\nHand-written intro.\n\n<!-- generated below -->\n\nold stuff\n")
    (field / "a.md").write_text("---\ntopics:\n- install\n- ollama\n---\nx\n")
    (field / "b.md").write_text("---\ntopics:\n- install\n---\ny\n")
    engrams.regenerate_index(field)
    text = (field / "index.md").read_text()
    assert "Hand-written intro." in text
    assert "old stuff" not in text
    assert "Topics across 2 pages:" in text
    assert text.index("- install (2)") < text.index("- ollama (1)")


def test_regenerate_index_without_marker_appends_one(tmp_path):
    field = tmp_path / ".engrams"; field.mkdir()
    (field / "index.md").write_text("intro only\n")
    engrams.regenerate_index(field)
    text = (field / "index.md").read_text()
    assert text.startswith("intro only\n\n<!-- generated below -->")
    assert "(no pages yet)" in text


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
    assert engrams.ref_changed(f"docs/a.md@{sha}", tmp_path) is None
    (tmp_path / "docs" / "a.md").write_text("two\n")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qam", "two"], check=True)
    reason = engrams.ref_changed(f"docs/a.md@{sha}", tmp_path)
    assert reason and "changed since cited (1 commit)" in reason
    assert "not found" in engrams.ref_changed("docs/a.md@deadbeef", tmp_path)
    assert "no commit cited" in engrams.ref_changed("docs/a.md", tmp_path)


def test_age_hint_by_kind():
    from datetime import UTC, datetime
    now = datetime(2026, 12, 1, tzinfo=UTC)
    old = {"kind": "environment", "updated": "2026-09-01T00:00:00Z"}
    assert "environment page, 91 days since written" == engrams.age_hint(old, now)
    assert engrams.age_hint({"kind": "procedure", "updated": "2026-09-01T00:00:00Z"}, now) == "procedure page, 91 days since written"
    assert engrams.age_hint({"kind": "finding", "updated": "2026-09-01T00:00:00Z"}, now) is None
    assert engrams.age_hint({"kind": "decision", "updated": "2020-01-01T00:00:00Z"}, now) is None
    verified = {"kind": "environment", "updated": "2026-01-01T00:00:00Z", "verified": "2026-11-20T00:00:00Z"}
    assert engrams.age_hint(verified, now) is None


def test_suspicion_ranks_ref_before_check_before_age(tmp_path, monkeypatch):
    from datetime import UTC, datetime
    import subprocess
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    sha = _repo(tmp_path)
    (tmp_path / "docs" / "a.md").write_text("two\n")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qam", "two"], check=True)
    fm = {"kind": "environment", "updated": "2026-01-01T00:00:00Z", "refs": [f"docs/a.md@{sha}"], "check": "false"}
    engrams.approve_check("false", "t.md")
    signals = engrams.suspicion(fm, tmp_path, run_checks=True, now=datetime(2026, 12, 1, tzinfo=UTC))
    assert [s for s, _ in signals] == ["ref", "check", "age"]
    without = engrams.suspicion(fm, tmp_path, run_checks=False, now=datetime(2026, 12, 1, tzinfo=UTC))
    assert [s for s, _ in without] == ["ref", "age"]
    assert engrams.marker(signals).startswith("  suspect: docs/a.md changed")
    assert "glance: environment page" in engrams.marker(signals)
    assert engrams.marker([]) == ""


def test_run_check_pass_fail_timeout():
    assert engrams.run_check("true") is None
    assert "exit 1" in engrams.run_check("false")
    engrams.CHECK_TIMEOUT = 1
    assert "timed out" in engrams.run_check("sleep 5")
    engrams.CHECK_TIMEOUT = 10


def test_distance_text_handles_substring_fallback():
    assert engrams.distance_text({"distance": 0.3333}) == "distance 0.333"
    assert engrams.distance_text({"distance": None}) == "string match"
    assert engrams.distance_text({}) == "string match"


def test_set_root_and_project_root(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert engrams.project_root() == tmp_path.resolve()
    engrams.set_root(tmp_path)
    assert [(s.name, s.kind, s.dir) for s in engrams.STORES] == [("project", "project", tmp_path.resolve() / ".engrams")]
    monkeypatch.delenv("CLAUDE_PROJECT_DIR")
    import subprocess
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    monkeypatch.chdir(tmp_path)
    assert engrams.project_root() == tmp_path.resolve()


def test_index_carries_format_line_and_check(tmp_path, capsys):
    field = tmp_path / ".engrams"; field.mkdir()
    (field / "index.md").write_text("intro\n")
    engrams.set_root(tmp_path)
    engrams.regenerate_index()
    text = (field / "index.md").read_text()
    assert "<!-- engrams format 1, written by engrams" in text
    assert engrams.read_format() == 1
    (field / "index.md").write_text(text.replace("format 1", "format 2"))
    with pytest.raises(SystemExit) as e:
        engrams.check_format()
    assert e.value.code == 2 and "newer engrams plugin" in capsys.readouterr().err
    (field / "index.md").write_text("intro only\n")
    assert engrams.read_format() == 0
    engrams.check_format()
    assert engrams.read_format() == 1


def test_init_appends_paragraph_once(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(engrams.shutil, "which", lambda name: None)
    (tmp_path / "CLAUDE.md").write_text("# Agent\n")
    engrams.main(["init"])
    text = (tmp_path / "CLAUDE.md").read_text()
    assert text.startswith("# Agent\n") and text.count(engrams.CLAUDE_MD_MARK) == 1
    assert (tmp_path / ".engrams" / "index.md").is_file()
    engrams.main(["init"])
    assert (tmp_path / "CLAUDE.md").read_text().count(engrams.CLAUDE_MD_MARK) == 1
    assert "nothing changed" in capsys.readouterr().out


def test_doctor_brief_guides_setup(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    engrams.main(["doctor", "--brief"])
    assert "not set up on this machine" in capsys.readouterr().out
    engrams.main(["setup", "--substring"]); capsys.readouterr()
    engrams.main(["doctor", "--brief"])
    assert "no .engrams/" in capsys.readouterr().out
    monkeypatch.setattr(engrams.shutil, "which", lambda name: None)
    engrams.main(["init"]); capsys.readouterr()
    engrams.main(["doctor", "--brief"])
    out = capsys.readouterr().out
    assert out.startswith("engrams: 0 pages, string search.") and "Persistence:" in out   # no git repo yet
    assert "not at the pin" not in out   # no tool installed: nothing to compare with the pin
    monkeypatch.setattr(engrams.shutil, "which", lambda name: "/usr/bin/memoryfield-tool")
    monkeypatch.setattr(engrams, "installed_rev", lambda: "deadbeef0000")
    engrams.main(["doctor", "--brief"])
    out = capsys.readouterr().out
    assert "memoryfield-tool is not at the pin" in out and "engrams doctor --fix" in out


def test_git_checks_and_init_staging(tmp_path, monkeypatch):
    import subprocess
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(engrams.shutil, "which", lambda name: None)
    engrams.set_root(tmp_path)
    assert engrams.git_checks()[0][1] == "this directory is a git repository"
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(".engrams/\n")
    engrams.main(["init"])
    states = {label: ok for ok, label, _ in engrams.git_checks()}
    assert states[".engrams is ignored by git"] is False
    assert states[".claude/settings.json does not exist"] is False
    (tmp_path / ".gitignore").write_text("")
    (tmp_path / ".claude").mkdir(); (tmp_path / ".claude" / "settings.json").write_text("{}")
    engrams.git_add([".engrams", "CLAUDE.md", ".claude/settings.json"])
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "x"], check=True)
    assert all(ok for ok, _, _ in engrams.git_checks())


def test_host_candidates_order(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert engrams.host_candidates() == [("http://127.0.0.1:11434", "default")]
    engrams.write_config_file({"embedding_host": "http://frame:11434"})
    assert engrams.host_candidates() == [("http://frame:11434", "engrams setup"), ("http://127.0.0.1:11434", "default")]
    monkeypatch.setenv("OLLAMA_HOST", "other:1")
    assert [c[1] for c in engrams.host_candidates()] == ["OLLAMA_HOST", "engrams setup", "default"]


def test_resolve_host_skips_a_dead_env_host(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("OLLAMA_HOST", "http://dead:11434")
    engrams.write_config_file({"embedding_host": "http://frame:11434"})
    monkeypatch.setattr(engrams, "host_answers", lambda url, timeout=2.0: url == "http://frame:11434")
    engrams._RESOLVED = None
    assert engrams.resolve_host() == ("http://frame:11434", "engrams setup", True)
    engrams._RESOLVED = None
    monkeypatch.setattr(engrams, "host_answers", lambda url, timeout=2.0: False)
    assert engrams.resolve_host() == ("http://dead:11434", "OLLAMA_HOST", False)
    engrams._RESOLVED = None


def test_search_json_never_calls_the_tool_on_a_dead_host(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(engrams, "host_answers", lambda url, timeout=2.0: False)
    engrams._RESOLVED = None
    called = []
    monkeypatch.setattr(engrams, "tool", lambda *a, **k: called.append(a))
    assert engrams.search_json("anything") == []
    assert called == []
    engrams._RESOLVED = None


def test_setup_writes_config(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setattr(engrams, "host_answers", lambda base, timeout=2.0, fresh=False: False)
    engrams.main(["setup", "--host", "frame:11434"])
    assert engrams.read_config() == {"semantic": True, "embedding_host": "http://frame:11434"}
    assert "does not answer yet" in capsys.readouterr().out
    engrams.main(["setup", "--local"])
    assert engrams.read_config()["embedding_host"] == "http://127.0.0.1:11434"
    engrams.main(["setup", "--substring"])
    assert engrams.read_config()["semantic"] is False and engrams.semantic_enabled() is False
    assert engrams.tool_env()["OLLAMA_HOST"] == engrams.NO_EMBEDDING_HOST
    monkeypatch.setenv("OLLAMA_HOST", "x:1")
    assert engrams.semantic_enabled() is True
    monkeypatch.delenv("OLLAMA_HOST")
    with pytest.raises(SystemExit):
        engrams.main(["setup", "--local", "--host", "x"])
    with pytest.raises(SystemExit):
        engrams.main(["setup", "--semantic", "--substring"])


def test_semantic_is_on_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert engrams.semantic_enabled() is True
    engrams.write_config_file({"semantic": False})
    assert engrams.semantic_enabled() is False


def test_merge_results_unions_and_ranks():
    a = [{"filename": "x.md", "summary": "X", "distance": 0.4}, {"filename": "y.md", "summary": "Y", "distance": None}]
    b = [{"filename": "y.md", "summary": "Y", "distance": None}, {"filename": "z.md", "summary": "Z", "distance": 0.2}]
    rows = engrams.merge_results([("one", a), ("two", b)])
    assert [r["filename"] for r in rows] == ["y.md", "z.md", "x.md"]     # matched by both terms first, then by distance
    assert rows[0]["matched"] == ["one", "two"]


def test_parse_results_skips_the_fallback_notice():
    noisy = 'embedding failed: Failed to connect to Ollama.\n[\n  {"filename": "a.md", "summary": "A", "distance": null}\n]\n'
    assert engrams.parse_results(noisy) == [{"filename": "a.md", "summary": "A", "distance": None}]
    assert engrams.parse_results("") == []
    assert engrams.parse_results("garbage") == []


def test_query_terms_keeps_identifiers_and_parts():
    assert engrams.query_terms("Why does install fail on a mac with pysqlite3-binary?") == ["install", "fail", "mac", "pysqlite3-binary", "pysqlite3", "binary"]
    assert engrams.query_terms("the memoryfield-tool wrapper") == ["memoryfield-tool", "memoryfield", "tool", "wrapper"]
    assert engrams.query_terms("the of and") == []


def test_string_search_and_hybrid_ranking(tmp_path, monkeypatch):
    field = tmp_path / ".engrams"; field.mkdir()
    (field / "index.md").write_text("intro\n")
    (field / "pysqlite3-install-override.md").write_text("---\ntitle: pysqlite3-binary blocks install\nsummary: the uv override\n---\nx\n")
    (field / "ollama-host-silent-hang.md").write_text("---\ntitle: A silent OLLAMA_HOST hangs the tool\nsummary: probe first\n---\nx\n")
    (field / "unrelated.md").write_text("---\ntitle: Something else\nsummary: nothing here\n---\nx\n")
    engrams.set_root(tmp_path)
    assert engrams.string_search(["intro"]) == []   # index.md is never a result on the string path either
    hits = engrams.string_search(["install", "pysqlite3", "hang"])
    assert {r["filename"]: r["matched"] for r in hits} == {"pysqlite3-install-override.md": ["install", "pysqlite3"], "ollama-host-silent-hang.md": ["hang"]}
    assert next(r for r in hits if r["filename"] == "pysqlite3-install-override.md")["head_terms"] == ["install", "pysqlite3"]   # hyphens are word boundaries
    (field / "verbs.md").write_text("---\ntitle: Something that lets the tool run\nsummary: it adds on top\n---\nx\n")
    verbs = next(r for r in engrams.string_search(["let", "add", "lets"]) if r["filename"] == "verbs.md")
    assert verbs["head_terms"] == ["lets"]   # "let" and "add" are substrings only
    (field / "body-only.md").write_text("---\ntitle: Elsewhere\nsummary: nothing\n---\nthe incident was filed as I113.\n")
    body = engrams.string_search(["i113"])
    assert [r["filename"] for r in body] == ["body-only.md"] and body[0]["head_terms"] == []
    monkeypatch.setattr(engrams, "semantic_enabled", lambda: True)
    monkeypatch.setattr(engrams, "search_json", lambda q: [
        {"filename": "unrelated.md", "summary": "nothing here", "distance": 0.30},
        {"filename": "pysqlite3-install-override.md", "summary": "the uv override", "distance": 0.40},
    ])
    rows = engrams.hybrid_search("why does install fail with pysqlite3")
    assert [r["filename"] for r in rows] == ["pysqlite3-install-override.md", "unrelated.md"]   # found by both beats a closer semantic-only hit
    assert rows[0]["via"] == ["semantic", "install", "pysqlite3"]
    monkeypatch.setattr(engrams, "semantic_enabled", lambda: False)
    rows = engrams.hybrid_search("hang")
    assert [r["filename"] for r in rows] == ["ollama-host-silent-hang.md"] and rows[0]["via"] == ["hang"]


def test_url_refs_are_kept_and_never_checked_in_search(tmp_path):
    assert engrams.fill_ref("https://example.com/x", tmp_path) == "https://example.com/x"
    assert engrams.ref_changed("https://example.com/x", tmp_path) is None
    assert engrams.suspicion({"refs": ["https://example.com/x"]}, tmp_path) == []


def test_url_status_gone_and_unreachable():
    import http.server, threading, socket
    class H(http.server.BaseHTTPRequestHandler):
        def do_HEAD(self):
            self.send_response(404 if self.path == "/gone" else 200); self.end_headers()
        def log_message(self, *a): pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), H); port = srv.server_port
    t = threading.Thread(target=srv.serve_forever, daemon=True); t.start()
    try:
        assert engrams.url_status(f"http://127.0.0.1:{port}/ok") is None
        sig, reason = engrams.url_status(f"http://127.0.0.1:{port}/gone")
        assert sig == "ref" and "gone" in reason
    finally:
        srv.shutdown()
    s = socket.socket(); s.bind(("127.0.0.1", 0)); closed = s.getsockname()[1]; s.close()
    sig, reason = engrams.url_status(f"http://127.0.0.1:{closed}/x", timeout=1.0)
    assert sig == "url" and "could not be reached" in reason
    assert engrams.marker([("url", "x could not be reached")]).startswith("  glance:")


def test_verify_requires_an_approved_check(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    field = tmp_path / ".engrams"; field.mkdir(); engrams.set_root(tmp_path)
    marker = tmp_path / "marker"
    (field / "evil.md").write_text(f"---\ntitle: E\nsummary: e\nkind: finding\ncheck: touch {marker}\n---\nx\n")
    monkeypatch.setattr(engrams, "tool", lambda *a, **k: type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    with pytest.raises(SystemExit):
        engrams.main(["verify", "evil.md"])
    assert not marker.exists() and "not approved" in capsys.readouterr().err
    (field / "bad.md").write_text("---\ntitle: B\nsummary: b\nkind: finding\ncheck: echo x > /tmp/x\n---\nx\n")
    with pytest.raises(SystemExit):
        engrams.main(["verify", "bad.md"])
    assert "not read-only" in capsys.readouterr().err


def _fake_tool(field, calls=None):
    """Stands in for memoryfield-tool: write stores the page in the field= store (else `field`), everything else succeeds silently."""
    def fake(*a, stdin=None, field=None, **k):
        if calls is not None:
            calls.append((a, field))
        target = next((s.dir for s in engrams.STORES if s.field == field), None) if field else None
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
    field = tmp_path / ".engrams"; field.mkdir(); engrams.set_root(tmp_path)
    (field / "cited.md").write_text(f"---\ntitle: C\nsummary: c\nkind: finding\nrefs:\n- docs/a.md@{sha}\n---\nx\n")
    (tmp_path / "docs" / "a.md").write_text("two\n")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qam", "two"], check=True)
    assert [s for s, _ in engrams.suspicion(engrams.page_frontmatter("cited.md"), tmp_path)] == ["ref"]
    monkeypatch.setattr(engrams, "tool", _fake_tool(field))
    monkeypatch.setattr(engrams, "reindex", lambda: None)
    engrams.main(["verify", "cited.md"])
    assert "verified cited.md" in capsys.readouterr().out
    fm = engrams.page_frontmatter("cited.md")
    assert fm["verified"] and fm["refs"][0].startswith("docs/a.md@") and not fm["refs"][0].endswith(sha)
    assert engrams.suspicion(fm, tmp_path) == []


def test_pull_prints_the_marker_above_each_page(tmp_path, monkeypatch, capsys):
    import subprocess
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    sha = _repo(tmp_path)
    field = tmp_path / ".engrams"; field.mkdir(); engrams.set_root(tmp_path)
    (field / "cited.md").write_text(f"---\ntitle: C\nsummary: cited page\nkind: finding\nrefs:\n- docs/a.md@{sha}\n---\nx\n")
    (field / "clean.md").write_text("---\ntitle: D\nsummary: clean page\nkind: finding\n---\ny\n")
    (tmp_path / "docs" / "a.md").write_text("two\n")
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qam", "two"], check=True)
    monkeypatch.setattr(engrams, "hybrid_search", lambda q: [
        {"filename": "cited.md", "summary": "cited page", "distance": 0.2, "via": ["semantic"]},
        {"filename": "clean.md", "summary": "clean page", "distance": 0.3, "via": ["semantic"]},
    ])
    monkeypatch.setattr(engrams, "tool", lambda *a, **k: type("P", (), {"returncode": 0, "stdout": f"<{a[-1]}>\n", "stderr": ""})())
    engrams.main(["pull", "anything"])
    out = capsys.readouterr().out
    assert out.startswith(engrams.READ_HEAD) and out.endswith(engrams.READ_TAIL)
    lines = out.splitlines()
    assert lines[1].startswith("cited.md: cited page") and "suspect: docs/a.md changed" in lines[1] and lines[2] == "<cited.md>"
    assert lines[3].startswith("clean.md: clean page") and "suspect" not in lines[3] and lines[4] == "<clean.md>"


def test_tool_refuses_an_unpinned_install(monkeypatch, capsys):
    monkeypatch.setattr(engrams, "_PIN_OK", False)
    monkeypatch.setattr(engrams.shutil, "which", lambda name: "/usr/bin/memoryfield-tool")
    monkeypatch.setattr(engrams, "installed_rev", lambda: "deadbeef0000")
    with pytest.raises(SystemExit):
        engrams.tool("validate")
    err = capsys.readouterr().err
    assert "at deadbee" in err and engrams.read_pin()["tool_rev"][:7] in err and "engrams doctor --fix" in err
    monkeypatch.setattr(engrams, "installed_rev", lambda: None)
    with pytest.raises(SystemExit):
        engrams.tool("validate")
    assert "an unknown commit" in capsys.readouterr().err
    monkeypatch.setattr(engrams, "installed_rev", lambda: engrams.read_pin()["tool_rev"])
    ran = []
    monkeypatch.setattr(engrams.subprocess, "run", lambda argv, **k: ran.append(argv) or type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    monkeypatch.setattr(engrams, "tool_env", lambda root=None: {})
    engrams.tool("validate")
    assert ran == [["memoryfield-tool", "validate"]] and engrams._PIN_OK


def test_first_token_uses_the_launcher_pair():
    assert engrams.first_token("uv tool install x") == "uv tool"
    assert engrams.first_token("uv --version") == "uv"
    assert engrams.first_token("ls -la") == "ls"
    assert engrams.first_token("git push origin main") == "git push"


def test_recall_filter_treats_distance_less_semantic_as_string_only():
    rows = [{"filename": "x.md", "summary": "X", "distance": None, "via": ["semantic", "pysqlite3"], "rare_terms": ["pysqlite3"], "head_terms": []}]
    assert [r["filename"] for r in engrams.recall_filter(rows)] == ["x.md"]


def test_recall_worthy_long_prompt_starting_with_no():
    assert engrams.recall_worthy("No, don't do that; instead debug why memoryfield-tool cannot reach the ollama host on port 11434 and fix it")
    assert not engrams.recall_worthy("No thanks, that is fine as it is, leave it there")


def test_guard_asks_for_approve_too():
    import json, subprocess
    shim = ROOT / "scripts" / "guard.sh"
    def run(cmd):
        return subprocess.run(["sh", str(shim)], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": "/tmp/engrams-doubt-notes"}), capture_output=True, text=True)
    assert "ask" in run("engrams approve x.md").stdout
    assert run("ls").stdout == ""               # a cwd containing the words does not trigger it


def test_guard_denies_a_raw_read_of_a_page():
    import json, subprocess
    shim = ROOT / "scripts" / "guard.sh"
    def run(cmd):
        return subprocess.run(["sh", str(shim)], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}), capture_output=True, text=True)
    def read(path):
        return subprocess.run(["sh", str(shim)], input=json.dumps({"tool_name": "Read", "tool_input": {"file_path": path}}), capture_output=True, text=True)
    for path in ("/repo/.engrams/a-page.md", ".engrams/a-page.md"):
        out = json.loads(read(path).stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", path
        assert "engrams read a-page.md" in out["hookSpecificOutput"]["permissionDecisionReason"]
    for path in ("/repo/.engrams/index.md", "/repo/docs/engrams/notes.md", "/repo/README.md"):
        assert read(path).stdout == "", path
    for cmd in ("cat .engrams/ollama-host.md", "cat /repo/.engrams/a-page.md | head", "head -20 .engrams/a-page.md", "sed -n 1,40p .engrams/a-page.md",
                "engrams search x 2>&1 || true; echo ---; cat .engrams/a-page.md; cat Makefile", "ls && cat .engrams/a-page.md", "(cat .engrams/a-page.md)", "ls\\ncat .engrams/a-page.md"):
        out = json.loads(run(cmd).stdout)
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny", cmd
        assert "engrams read" in out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "engrams doctor --fix" in out["hookSpecificOutput"]["permissionDecisionReason"]
    for cmd in ("cat .engrams/index.md", "engrams read a-page.md", "cat README.md", "ls .engrams", "cat >> .engrams/a-page.md <<EOF"):
        assert run(cmd).stdout == "", cmd


def test_guard_asks_only_for_network_doubt():
    import json, subprocess
    shim = ROOT / "scripts" / "guard.sh"
    def run(cmd):
        return subprocess.run(["sh", str(shim)], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}), capture_output=True, text=True)
    assert run("engrams doubt").stdout == ""
    assert run("git status").stdout == ""
    out = json.loads(run("engrams doubt --network").stdout)
    assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


def test_recall_gates_and_filter():
    assert not engrams.recall_worthy("yes")
    assert not engrams.recall_worthy("Yes, it is completed. Your suggested timebox works fine by me.")
    assert not engrams.recall_worthy("3> agree, and the second one too, please go ahead")
    assert not engrams.recall_worthy("/plugin install engrams@dokidlc and then something long enough")
    assert engrams.recall_worthy("why does installing memoryfield-tool fail on this mac")
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
    assert [r["filename"] for r in engrams.recall_filter(rows)] == ["both-rare.md", "close.md", "ident.md"]
    assert [r["filename"] for r in engrams.recall_filter(rows[4:])] == ["close.md", "ident.md", "titled.md"]


def test_recall_line_names_read_commands_and_is_bounded(tmp_path, monkeypatch):
    engrams.set_root(tmp_path); (tmp_path / ".engrams").mkdir()
    rows = [{"filename": f"page-{i}.md", "summary": "s" * 150, "distance": 0.2, "via": ["semantic"]} for i in range(3)]
    line = engrams.recall_line(rows)
    assert line.startswith("engrams: ") and "`engrams read page-0.md`" in line
    assert len(line.encode()) <= engrams.RECALL_MAX_BYTES
    assert "page-2.md" not in line or line.count("`engrams read") == 3   # whole entries dropped, never cut
    assert engrams.recall_line([]) == ""


def test_recall_hook_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    field = tmp_path / ".engrams"; field.mkdir()
    (field / "pysqlite3-install-override.md").write_text("---\ntitle: pysqlite3-binary blocks install\nsummary: the uv override\ntopics: [install]\nkind: environment\n---\nx\n")
    engrams.write_config_file({"semantic": False})
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": "why does uv tool install memoryfield-tool fail with pysqlite3-binary"})))
    engrams.main(["recall"])
    out = capsys.readouterr().out
    assert "`engrams read pysqlite3-install-override.md`" in out
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": "yes"})))
    engrams.main(["recall"]); assert capsys.readouterr().out == ""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "uv tool install memoryfield-tool"}, "error": "Exit code 1\nno wheels for pysqlite3-binary"})))
    engrams.main(["recall", "--failure"])
    out = json.loads(capsys.readouterr().out)
    assert "pysqlite3-install-override.md" in out["hookSpecificOutput"]["additionalContext"]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls /nope"}, "error": "Exit code 2"})))
    engrams.main(["recall", "--failure"])
    assert capsys.readouterr().out == ""          # nothing but the exit code: stay silent
    rows = engrams.read_log()
    assert [r["cmd"] for r in rows] == ["recall", "failure", "recall", "failure"]
    assert "query" not in rows[0]                 # prompt text is not logged


def test_show_hooks_shows_each_hook_line_to_the_user(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s5")
    monkeypatch.setattr(engrams.shutil, "which", lambda name: None)
    field = tmp_path / ".engrams"; field.mkdir()
    (field / "pysqlite3-install-override.md").write_text("---\ntitle: pysqlite3-binary blocks install\nsummary: the uv override\ntopics: [install]\nkind: environment\n---\nx\n")
    (tmp_path / ".claude").mkdir(); (tmp_path / ".claude" / "engrams.toml").write_text("show_hooks = true\n")
    engrams.write_config_file({"semantic": False})
    def run(argv, payload):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload))); engrams.main(argv); return capsys.readouterr().out
    out = json.loads(run(["recall"], {"prompt": "why does uv tool install memoryfield-tool fail with pysqlite3-binary"}))
    assert out["systemMessage"] == out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit" and "pysqlite3-install-override.md" in out["systemMessage"]
    out = json.loads(run(["doctor", "--brief", "--hook"], {"hook_event_name": "SessionStart", "session_id": "s5"}))
    assert out["systemMessage"].startswith("engrams: 1 page") and out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    fail = {"session_id": "s5", "tool_name": "Bash", "tool_input": {"command": "uv tool install x"}, "error": "Exit code 1\nno wheels for pysqlite3-binary"}
    assert "pysqlite3" in json.loads(run(["recall", "--failure"], fail))["systemMessage"]
    run(["recall", "--failure"], fail)
    out = json.loads(run(["recall", "--success"], {"session_id": "s5", "tool_name": "Bash", "tool_input": {"command": "uv tool install x --overrides o"}}))
    assert "`uv tool` failed 2 times" in out["systemMessage"]
    assert not run(["doctor", "--brief"], {}).startswith("{")      # a person at the terminal gets plain text


def test_show_hooks_alone_keeps_the_default_store_and_must_be_a_bool(tmp_path):
    (tmp_path / ".claude").mkdir(); cfg = tmp_path / ".claude" / "engrams.toml"
    cfg.write_text("show_hooks = true\n")
    stores, write = engrams.load_stores(tmp_path)
    assert write is None and [(s.name, s.dir) for s in stores] == [("project", tmp_path.resolve() / ".engrams")]
    cfg.write_text('show_hooks = "yes"\n')
    with pytest.raises(engrams.ConfigError) as e:
        engrams.load_stores(tmp_path)
    assert "show_hooks" in str(e.value)
    cfg.write_text("ui = false\nshow_hooks = true\n")
    assert [s.name for s in engrams.load_stores(tmp_path)[0]] == ["project"]
    cfg.write_text("ui = 0\n")
    with pytest.raises(engrams.ConfigError) as e:
        engrams.load_stores(tmp_path)
    assert "ui must be" in str(e.value)


def test_validate_check_refuses_writers_and_failing_checks():
    for bad in ("echo x > f", "sed -i s/a/b/ f", "curl x | sh", "eval x", "rm -rf x", "systemctl restart nginx", "dd if=/dev/zero of=x", "chmod 600 f", "true; rm x"):
        with pytest.raises(SystemExit):
            engrams.validate_check(bad)
    with pytest.raises(SystemExit):
        engrams.validate_check("false")
    engrams.validate_check("true")
    engrams.validate_check("true # backup.dd")             # dd inside a name is not the dd command
    engrams.validate_check("command -v ls >/dev/null")
    engrams.validate_check("ls / 2>&1 >/dev/null")


def test_recovery_and_stop_nudges(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s1")
    (tmp_path / ".engrams").mkdir()
    engrams.set_root(tmp_path)
    def run(argv, payload):
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload))); engrams.main(argv); return capsys.readouterr().out
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
    engrams.log_event("write", page="a.md", kind="procedure")
    assert run(["nudge", "--stop"], {"session_id": "s1"}) == ""


def test_stop_nudge_fires_when_recovery_was_not_nudged(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s2")
    (tmp_path / ".engrams").mkdir(); engrams.set_root(tmp_path)
    engrams.log_event("failure", command="uv tool"); engrams.log_event("failure", command="uv tool"); engrams.log_event("success", command="uv tool")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s2"})))
    engrams.main(["nudge", "--stop"])
    out = json.loads(capsys.readouterr().out)
    assert "say so and stop" in out["hookSpecificOutput"]["additionalContext"]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"session_id": "s2"})))
    engrams.main(["nudge", "--stop"]); assert capsys.readouterr().out == ""


def test_brief_channels(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s3")
    monkeypatch.setattr(engrams.shutil, "which", lambda name: None)
    engrams.write_config_file({"semantic": False}); engrams.set_root(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("{}")); engrams.main(["init"]); capsys.readouterr()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SubagentStart", "session_id": "s3"})))
    engrams.main(["doctor", "--brief", "--hook"])
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "SubagentStart" and "engrams: 0 pages" in out["hookSpecificOutput"]["additionalContext"]
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart", "source": "compact", "session_id": "s3"})))
    engrams.main(["doctor", "--brief", "--hook"])
    assert "just compacted" in capsys.readouterr().out
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart", "source": "startup", "session_id": "s3"})))
    engrams.main(["doctor", "--brief", "--hook"])
    assert "just compacted" not in capsys.readouterr().out


def test_stats(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "s4"); engrams.set_root(tmp_path)
    engrams.log_event("search", query="q", hits=1, pages=["a.md"]); engrams.log_event("read", pages=["a.md"]); engrams.log_event("write", page="a.md", kind="finding")
    engrams.main(["stats"])
    out = capsys.readouterr().out
    assert "1 session" in out and "read after a search or recall named it: 1/1" in out


def test_approved_checks_gate_doubt(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st")); engrams.set_root(tmp_path)
    fm = {"kind": "finding", "check": "true", "updated": "2026-09-04T00:00:00Z"}
    sig = engrams.suspicion(fm, tmp_path, run_checks=True)
    assert sig and sig[0][0] == "unapproved"
    engrams.approve_check("true", "x.md")
    assert engrams.suspicion(fm, tmp_path, run_checks=True) == []
    engrams.approve_check("false", "y.md")
    assert engrams.suspicion({"kind": "finding", "check": "false"}, tmp_path, run_checks=True)[0][0] == "check"


def test_terms_keep_dotted_numbers_whole():
    assert engrams.query_terms("the NAS at 192.168.1.10 runs 5.2.9 and ollama-host-3") == ["nas", "192.168.1.10", "runs", "5.2.9", "ollama-host-3", "ollama", "host"]


def test_doctor_brief_returns_with_stdin_held_open(tmp_path):
    """A script that inherits an open pipe must not hang: without --hook the command never reads stdin."""
    import os, select, subprocess
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path / "cfg"), XDG_STATE_HOME=str(tmp_path / "st"), CLAUDE_PROJECT_DIR=str(tmp_path))
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    proc = subprocess.Popen([str(ROOT / "bin" / "engrams"), "doctor", "--brief"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, text=True)
    try:
        ready, _, _ = select.select([proc.stdout], [], [], 60)   # stdin stays open the whole time
        assert ready, "doctor --brief did not print within 60 seconds with stdin held open"
        assert "engrams: not set up" in proc.stdout.readline()
    finally:
        proc.kill()


# --- stores -------------------------------------------------------------------


def _two_stores(tmp_path, monkeypatch, write=None, remote_url="https://example.com/agent-engrams.git"):
    """A project store at .engrams and a remote store whose clone directory exists (no git needed)."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    (tmp_path / ".claude").mkdir(exist_ok=True)
    head = f'write = "{write}"\n' if write else ""
    (tmp_path / ".claude" / "engrams.toml").write_text(
        head + '[stores.project]\nkind = "project"\npath = ".engrams"\n\n[stores.agent]\nkind = "remote"\n'
        f'url = "{remote_url}"\n')
    (tmp_path / ".engrams").mkdir(exist_ok=True)
    engrams.set_root(tmp_path)
    agent = engrams.store_named("agent")
    agent.dir.mkdir(parents=True, exist_ok=True)
    return engrams.store_named("project"), agent


def _page(store_dir, name, summary="s", extra=""):
    (store_dir / name).write_text(f"---\ntitle: T\nsummary: {summary}\ntopics: [t]\nkind: finding\n{extra}---\nbody\n")


def test_load_stores_defaults_to_one_project_store(tmp_path):
    stores, write = engrams.load_stores(tmp_path)
    assert write is None and len(stores) == 1
    s = stores[0]
    assert (s.name, s.kind, s.dir, s.field) == ("project", "project", tmp_path.resolve() / ".engrams", engrams.field_name(tmp_path))


def test_load_stores_reads_project_and_remote(tmp_path, monkeypatch):
    project, agent = _two_stores(tmp_path, monkeypatch, write="agent")
    assert engrams.WRITE_DEFAULT == "agent" and [s.name for s in engrams.STORES] == ["project", "agent"]
    assert agent.kind == "remote" and agent.url == "https://example.com/agent-engrams.git"
    assert agent.dir.parent == tmp_path / "data" / "dokidlc-engrams" / "stores"
    assert engrams.re.fullmatch(r"agent-[0-9a-f]{8}", agent.dir.name) and agent.field == agent.dir.name
    assert project.field == engrams.field_name(tmp_path)


def test_load_stores_rejects_bad_config(tmp_path):
    (tmp_path / ".claude").mkdir()
    cfg = tmp_path / ".claude" / "engrams.toml"
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
        with pytest.raises(engrams.ConfigError) as e:
            engrams.load_stores(tmp_path)
        assert ".claude/engrams.toml" in str(e.value), text


def test_config_error_kills_commands_and_silences_hooks(tmp_path, monkeypatch, capsys):
    import io
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    (tmp_path / ".claude").mkdir(); (tmp_path / ".claude" / "engrams.toml").write_text("not toml [")
    with pytest.raises(SystemExit):
        engrams.main(["search", "x"])
    assert ".claude/engrams.toml" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"prompt": "a prompt long enough to be worth a recall search here"})))
    engrams.main(["recall"])
    engrams.main(["doctor", "--brief"])
    assert capsys.readouterr() == ("", "")


def test_config_text_lists_every_store(tmp_path, monkeypatch):
    project, agent = _two_stores(tmp_path, monkeypatch)
    text = engrams.config_text(tmp_path)
    assert f"[memoryfields.{project.field}]" in text and f"[memoryfields.{agent.field}]" in text
    assert f'location = "{agent.dir.resolve()}"' in text


def test_resolve_page_bare_prefixed_and_ambiguous(tmp_path, monkeypatch, capsys):
    project, agent = _two_stores(tmp_path, monkeypatch)
    _page(project.dir, "only-here.md"); _page(agent.dir, "both.md"); _page(project.dir, "both.md")
    assert engrams.resolve_page("only-here.md") == (project, "only-here.md")
    assert engrams.resolve_page("agent/both.md") == (agent, "both.md")
    with pytest.raises(SystemExit):
        engrams.resolve_page("both.md")
    err = capsys.readouterr().err
    assert "project/both.md" in err and "agent/both.md" in err
    with pytest.raises(SystemExit):
        engrams.resolve_page("nostore/x.md")


def test_write_store_order(tmp_path, monkeypatch):
    project, agent = _two_stores(tmp_path, monkeypatch)
    assert engrams.write_store("agent") == agent
    assert engrams.write_store(None) == project                    # no write key: the project store
    _two_stores(tmp_path, monkeypatch, write="agent")
    assert engrams.write_store(None) == engrams.store_named("agent")
    (tmp_path / ".claude" / "engrams.toml").write_text('[stores.solo]\nkind = "remote"\nurl = "u"\n')
    engrams.set_root(tmp_path)
    assert engrams.write_store(None).name == "solo"               # the only store


def test_write_refuses_a_name_in_another_store(tmp_path, monkeypatch, capsys):
    import io
    project, agent = _two_stores(tmp_path, monkeypatch)
    _page(agent.dir, "taken.md")
    monkeypatch.setattr(engrams, "tool", _fake_tool(project.dir))
    monkeypatch.setattr(engrams, "reindex", lambda: None)
    argv = ["write", "taken.md", "--title", "T", "--summary", "s", "--topics", "t", "--kind", "finding"]
    monkeypatch.setattr("sys.stdin", io.StringIO("x\n\n## Sources\n\n- y\n"))
    with pytest.raises(SystemExit):
        engrams.main(argv)
    assert "already exists in store agent" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO("x\n\n## Sources\n\n- y\n"))
    engrams.main(argv + ["--store", "project"])
    assert (project.dir / "taken.md").is_file()


def test_read_and_pull_pass_the_field(tmp_path, monkeypatch, capsys):
    project, agent = _two_stores(tmp_path, monkeypatch)
    _page(project.dir, "p.md"); _page(agent.dir, "a.md")
    calls = []
    monkeypatch.setattr(engrams, "tool", _fake_tool(project.dir, calls))
    engrams.main(["read", "p.md", "agent/a.md"])
    assert [(a[0], a[-1], f) for a, f in calls] == [("read", "p.md", project.field), ("read", "a.md", agent.field)]
    calls.clear()
    monkeypatch.setattr(engrams, "hybrid_search", lambda q: [{"filename": "a.md", "store": "agent", "summary": "s", "distance": 0.2, "via": ["semantic"]}])
    engrams.main(["pull", "x"])
    assert calls == [(("read", "--no-line-numbers", "a.md"), agent.field)]


def test_search_prefixes_store_with_two_stores(tmp_path, monkeypatch, capsys):
    project, agent = _two_stores(tmp_path, monkeypatch)
    _page(project.dir, "ollama-p.md", "ollama in project"); _page(agent.dir, "ollama-a.md", "ollama in agent")
    engrams.write_config_file({"semantic": False})
    engrams.main(["search", "ollama"])
    lines = capsys.readouterr().out.splitlines()
    assert sorted(line.split(":")[0] for line in lines) == ["agent/ollama-a.md", "project/ollama-p.md"]
    engrams.main(["search", "--json", "ollama"])
    rows = json.loads(capsys.readouterr().out)
    assert sorted((r["store"], r["filename"]) for r in rows) == [("agent", "ollama-a.md"), ("project", "ollama-p.md")]
    (tmp_path / ".claude" / "engrams.toml").unlink(); engrams.set_root(tmp_path)
    engrams.main(["search", "ollama"])
    assert capsys.readouterr().out.startswith("ollama-p.md: ")      # one store: no prefix


# --- auto commit --------------------------------------------------------------


def _git(repo, *args):
    import subprocess
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def _project(tmp_path, monkeypatch):
    """A git repository with a committed .engrams/index.md, isolated from the user's git config."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null"); monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "t"); monkeypatch.setenv(f"GIT_{who}_EMAIL", "t@t")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg")); monkeypatch.delenv("OLLAMA_HOST", raising=False)
    _repo(tmp_path)
    field = tmp_path / ".engrams"; field.mkdir()
    (field / "index.md").write_text(engrams.INDEX_TEMPLATE)
    _git(tmp_path, "add", ".engrams"); _git(tmp_path, "commit", "-qm", "engrams")
    engrams.set_root(tmp_path)
    monkeypatch.setattr(engrams, "tool", _fake_tool(field))
    monkeypatch.setattr(engrams, "reindex", lambda: None)
    return field


def _write(monkeypatch, name, *extra):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("x\n\n## Sources\n\n- y\n"))
    engrams.main(["write", name, "--title", "T", "--summary", "s", "--topics", "t", "--kind", "finding", *extra])


def test_commit_store_commits_only_memory_paths(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    (tmp_path / "staged.txt").write_text("s\n"); _git(tmp_path, "add", "staged.txt")
    (tmp_path / "docs" / "a.md").write_text("edited\n")
    _write(monkeypatch, "new-page.md")
    files = _git(tmp_path, "show", "--name-only", "--format=%s", "HEAD").split()
    assert files[:3] == ["engrams:", "write", "new-page.md"]
    assert sorted(files[3:]) == [".engrams/index.md", ".engrams/new-page.md"]
    status = _git(tmp_path, "status", "--porcelain")
    assert "A  staged.txt" in status and " M docs/a.md" in status


def test_commit_picks_up_an_earlier_uncommitted_page(tmp_path, monkeypatch):
    field = _project(tmp_path, monkeypatch)
    _page(field, "left-behind.md")
    _write(monkeypatch, "next.md")
    assert ".engrams/left-behind.md" in _git(tmp_path, "show", "--name-only", "--format=", "HEAD").split()


def test_commit_store_runs_only_without_an_operation_in_progress(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    head = _git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / ".git" / "MERGE_HEAD").write_text(head)
    _write(monkeypatch, "during-merge.md")
    assert (tmp_path / ".engrams" / "during-merge.md").is_file()
    assert _git(tmp_path, "rev-parse", "HEAD") == head
    assert "not committed: a merge or rebase is in progress" in capsys.readouterr().err


def test_commit_store_reports_a_failing_hook(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    hook = tmp_path / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho refused by hook >&2\nexit 1\n"); hook.chmod(0o755)
    head = _git(tmp_path, "rev-parse", "HEAD")
    _write(monkeypatch, "hooked.md")                        # exits 0: no SystemExit
    assert (tmp_path / ".engrams" / "hooked.md").is_file() and _git(tmp_path, "rev-parse", "HEAD") == head
    assert "written, not committed: refused by hook" in capsys.readouterr().err


def test_verify_delete_index_commit(tmp_path, monkeypatch):
    field = _project(tmp_path, monkeypatch)
    _write(monkeypatch, "life.md")
    engrams.main(["verify", "life.md"])
    assert _git(tmp_path, "log", "-1", "--format=%s") == "engrams: verify life.md\n"
    engrams.main(["delete", "life.md"])
    assert _git(tmp_path, "log", "-1", "--format=%s") == "engrams: delete life.md\n"
    assert not (field / "life.md").exists() and "life.md" not in _git(tmp_path, "ls-files")
    (field / "index.md").write_text("intro\n")
    engrams.main(["index"])
    assert _git(tmp_path, "log", "-1", "--format=%s") == "engrams: index\n"


def test_store_lock_serializes_two_writers(tmp_path, monkeypatch, capsys):
    import threading
    field = _project(tmp_path, monkeypatch)
    store = engrams.project_store()
    _page(field, "one.md"); _page(field, "two.md")
    errors = []

    def commit(msg):
        try:
            engrams.save(store, msg)
        except Exception as e:   # pragma: no cover - surfaced by the assert
            errors.append(e)
    with engrams.store_lock(store.field):
        threads = [threading.Thread(target=commit, args=(f"engrams: write {n}",)) for n in ("one.md", "two.md")]
        for t in threads:
            t.start()
        import time; time.sleep(0.3)                          # both wait on the lock this test holds
        assert _git(tmp_path, "status", "--porcelain", "--", ".engrams").count("??") == 2
    for t in threads:
        t.join()
    assert not errors and "index.lock" not in capsys.readouterr().err
    assert _git(tmp_path, "status", "--porcelain", "--", ".engrams") == ""


def test_doctor_brief_counts_uncommitted(tmp_path, monkeypatch, capsys):
    field = _project(tmp_path, monkeypatch)
    engrams.write_config_file({"semantic": False})
    engrams.main(["doctor", "--brief"])
    assert "not committed" not in capsys.readouterr().out
    _page(field, "loose.md")
    engrams.main(["doctor", "--brief"])
    assert "1 store change not committed." in capsys.readouterr().out


def test_brief_does_not_warn_on_page_count(tmp_path, monkeypatch, capsys):
    field = _project(tmp_path, monkeypatch)
    engrams.write_config_file({"semantic": False})
    for i in range(51):
        _page(field, f"page-{i}.md")
    engrams.main(["doctor", "--brief"])
    out = capsys.readouterr().out
    assert out.startswith("engrams: 51 pages") and "is a lot" not in out


def _index(tmp_path, monkeypatch, vectors, table="pages", root=None):
    """memoryfield-tool's index for the project store: one row per page, 768 float32 values each."""
    import sqlite3, struct
    monkeypatch.setattr(engrams, "cache_dir", lambda: tmp_path / "cache")
    path = tmp_path / "cache" / "memoryfield-tool" / "indexes" / engrams.field_name(root or tmp_path) / f"{engrams.read_pin()['model_code']}.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE {table} (filename TEXT PRIMARY KEY, frontmatter JSON NOT NULL, last_modified DATETIME NOT NULL, sha256_hash BLOB NOT NULL, embedding BLOB NOT NULL)")
    for name, head in vectors.items():
        blob = struct.pack("<768f", *(list(head) + [0.0] * (768 - len(head))))
        con.execute(f"INSERT INTO {table} VALUES (?, '{{}}', '2026-10-03', ?, ?)", (name, name.encode(), blob))
    con.commit(); con.close()
    return path


# a.md and b.md are 0.05 apart; far.md is at distance 1 from both; index.md never counts
_CLOSE = {"a.md": (1.0, 0.0), "b.md": (0.95, 0.3122499), "far.md": (0.0, 0.0, 1.0), "index.md": (1.0, 0.0)}


def test_near_duplicates_names_the_close_pair(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    _index(tmp_path, monkeypatch, _CLOSE)
    assert engrams.near_duplicates() == [(0.05, "a.md", "b.md")]


def test_near_duplicates_without_an_index_is_empty(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    monkeypatch.setattr(engrams, "cache_dir", lambda: tmp_path / "cache")
    assert engrams.near_duplicates() == []                      # no index file
    _index(tmp_path, monkeypatch, _CLOSE, table="other")
    assert engrams.near_duplicates() == []                      # a layout the pinned tool does not write


def test_near_duplicates_reuses_the_cached_result(tmp_path, monkeypatch):
    _project(tmp_path, monkeypatch)
    _index(tmp_path, monkeypatch, _CLOSE)
    first = engrams.near_duplicates()
    calls = []
    real = engrams.page_vectors
    monkeypatch.setattr(engrams, "page_vectors", lambda: calls.append(1) or real())
    assert engrams.near_duplicates() == first and calls == []
    other = tmp_path / "other"; (other / ".engrams").mkdir(parents=True)
    _index(tmp_path, monkeypatch, {"c.md": (1.0, 0.0), "d.md": (0.96, 0.28)}, root=other)
    engrams.set_root(other)
    assert engrams.near_duplicates() == [(0.04, "c.md", "d.md")] and calls == [1]
    engrams.set_root(tmp_path)
    assert {str(tmp_path), str(other)} <= set(engrams.read_state_json("pairs.json"))   # one root's write keeps the other's entry
    assert engrams.near_duplicates() == first and calls == [1]


def test_near_duplicates_survives_a_bad_cache_and_a_short_read(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    engrams.write_config_file({"semantic": True})
    _index(tmp_path, monkeypatch, _CLOSE)
    first = engrams.near_duplicates()
    state = engrams.read_state_json("pairs.json")
    state[str(tmp_path)]["pairs"] = [[0.05, "a.md"]]            # a shape this version never wrote
    engrams.write_state_json("pairs.json", state)
    assert engrams.near_duplicates() == first
    state[str(tmp_path)]["pairs"] = [["x", "a.md", "b.md"]]     # a distance doctor could not print
    engrams.write_state_json("pairs.json", state)
    assert engrams.near_duplicates() == first
    engrams.write_state_json("pairs.json", {})
    real = engrams.page_vectors
    monkeypatch.setattr(engrams, "page_vectors", lambda: {})     # the index was locked between the two reads
    assert engrams.near_duplicates() == []
    monkeypatch.setattr(engrams, "page_vectors", real)
    assert engrams.near_duplicates() == first                    # the short result was not kept
    engrams.write_state_json("pairs.json", {})
    assert engrams.near_duplicates(budget=0) == [] and engrams.read_state_json("pairs.json") == {}
    monkeypatch.setattr(engrams, "near_duplicates", lambda budget=None: 1 / 0)
    engrams.main(["doctor", "--brief"])                          # a hook never fails on this signal
    assert capsys.readouterr().out.startswith("engrams: 0 pages")


def test_doctor_names_near_duplicate_pairs(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    engrams.write_config_file({"semantic": True})
    _index(tmp_path, monkeypatch, _CLOSE)
    with pytest.raises(SystemExit):
        engrams.main(["doctor"])
    assert "note near-duplicate pages (distance 0.050): a.md | b.md" in capsys.readouterr().out


def test_brief_counts_near_duplicate_pairs(tmp_path, monkeypatch, capsys):
    _project(tmp_path, monkeypatch)
    engrams.write_config_file({"semantic": True})
    engrams.main(["doctor", "--brief"])
    assert "near-duplicate" not in capsys.readouterr().out
    _index(tmp_path, monkeypatch, _CLOSE)
    engrams.main(["doctor", "--brief"])
    assert "1 near-duplicate pair: engrams doctor names them; merge each or keep both." in capsys.readouterr().out
    engrams.write_config_file({"semantic": False})               # string mode: nothing refreshes the index
    engrams.main(["doctor", "--brief"])
    assert "near-duplicate" not in capsys.readouterr().out


def test_brief_reports_a_slow_scan(tmp_path, monkeypatch, capsys):
    field = _project(tmp_path, monkeypatch)
    engrams.write_config_file({"semantic": False})
    _page(field, "one.md")
    engrams.main(["doctor", "--brief"])
    assert "start scan" not in capsys.readouterr().out
    monkeypatch.setattr(engrams, "SCAN_BUDGET", 0)
    engrams.main(["doctor", "--brief"])
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
    (proj / ".claude" / "engrams.toml").write_text(
        f'write = "{write}"\n\n[stores.project]\nkind = "project"\npath = ".engrams"\n\n[stores.agent]\nkind = "remote"\nurl = "{bare}"\n')
    engrams.set_root(proj)
    agent = engrams.store_named("agent")
    assert engrams.clone_store(agent) is None
    monkeypatch.setattr(engrams, "tool", _fake_tool(proj / ".engrams"))
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
    engrams.main(["stores", "add", "agent", str(bare), "--default"])
    text = (proj / ".claude" / "engrams.toml").read_text()
    assert 'write = "agent"' in text and "[stores.project]" in text and f'url = "{bare}"' in text
    agent = engrams.store_named("agent")
    assert (agent.dir / "index.md").is_file()
    assert _git(bare, "log", "-1", "--format=%s", "main") == "engrams: create store agent\n"
    assert _git(proj, "show", "--name-only", "--format=%s", "HEAD").split() == ["engrams:", "add", "store", "agent", ".claude/engrams.toml"]


def test_push_store_rebases_once(tmp_path, monkeypatch, capsys):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    _push_page(_other_clone(tmp_path, bare), "theirs.md")
    _write(monkeypatch, "mine.md")
    assert "not pushed" not in capsys.readouterr().err
    tree = _git(bare, "ls-tree", "--name-only", "main").split()
    assert "theirs.md" in tree and "mine.md" in tree
    assert "Engrams-Project: " in _git(bare, "log", "-1", "--format=%B", "main")


def test_push_store_conflict_keeps_the_commit(tmp_path, monkeypatch, capsys):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    _write(monkeypatch, "shared.md")
    _push_page(_other_clone(tmp_path, bare), "shared.md", "their version\n")
    _write(monkeypatch, "shared.md", "--summary", "mine changed")
    err = capsys.readouterr().err
    assert "not pushed" in err and "engrams sync" in err
    assert not engrams.rebase_in_progress(agent.repo)
    assert _git(agent.repo, "log", "-1", "--format=%s") == "engrams: write shared.md\n"
    assert engrams.unpushed(agent) == 1


def test_sync_commits_pulls_and_pushes(tmp_path, monkeypatch, capsys):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    monkeypatch.setattr(engrams, "reindex", lambda: None)
    _page(agent.dir, "loose.md")
    _push_page(_other_clone(tmp_path, bare), "theirs.md")
    engrams.main(["sync"])
    out = capsys.readouterr().out
    assert out.startswith("agent: committed 1 file, pulled 1 file, pushed")
    tree = _git(bare, "ls-tree", "--name-only", "main").split()
    assert "loose.md" in tree and "theirs.md" in tree and engrams.unpushed(agent) == 0


def test_project_store_never_pushes(tmp_path, monkeypatch):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    project_remote = tmp_path / "project.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(project_remote))
    _git(proj, "remote", "add", "origin", str(project_remote))
    _write(monkeypatch, "local.md", "--store", "project")
    assert _git(proj, "log", "-1", "--format=%s") == "engrams: write local.md\n"
    assert _git(project_remote, "rev-list", "--all") == ""          # nothing was pushed


def test_brief_pulls_only_at_session_start(tmp_path, monkeypatch, capsys):
    import io
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    engrams.write_config_file({"semantic": False})
    started = []
    monkeypatch.setattr(engrams, "start_background", lambda argv: started.append(argv))
    _push_page(_other_clone(tmp_path, bare), "theirs.md")
    head = _git(agent.repo, "rev-parse", "HEAD")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SubagentStart"})))
    engrams.main(["doctor", "--brief", "--hook"]); capsys.readouterr()
    assert _git(agent.repo, "rev-parse", "HEAD") == head and not started
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart", "source": "startup"})))
    engrams.main(["doctor", "--brief", "--hook"])
    assert (agent.dir / "theirs.md").is_file() and "Pulled 1 page" in capsys.readouterr().out
    assert started and started[0][-1] == "index"


def test_doctor_brief_counts_unpushed(tmp_path, monkeypatch, capsys):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    engrams.write_config_file({"semantic": False})
    engrams.main(["doctor", "--brief"])
    assert "not pushed" not in capsys.readouterr().out
    _page(agent.dir, "local-only.md"); _git(agent.repo, "add", "."); _git(agent.repo, "commit", "-qm", "local")
    engrams.main(["doctor", "--brief"])
    assert "1 store commit not pushed (engrams sync)." in capsys.readouterr().out


def test_project_id_normalizes_origin(tmp_path):
    same = ["git@github.com:DaftDoki/agent-builder.git", "https://github.com/daftdoki/agent-builder",
            "ssh://git@github.com:22/daftdoki/agent-builder.git", "https://user@github.com/DaftDoki/agent-builder.git/"]
    assert {engrams.normalize_origin(u) for u in same} == {"github.com/daftdoki/agent-builder"}
    plain = tmp_path / "My_Project"; plain.mkdir()
    assert engrams.project_id(plain) == "my-project"


def test_remote_page_gets_project_and_prefixed_refs(tmp_path, monkeypatch):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    _write(monkeypatch, "cites.md", "--ref", "docs/a.md")
    fm = engrams.page_frontmatter("cites.md", agent)
    pid = engrams.project_id()
    sha = _git(proj, "log", "-1", "--format=%h", "--", "docs/a.md").strip()
    assert fm["project"] == pid and fm["refs"] == [f"{pid}:docs/a.md@{sha}"]
    assert engrams.suspicion(fm) == []


def test_ref_in_another_project_gives_no_signal(tmp_path, monkeypatch, capsys):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    marker = tmp_path / "ran"
    _page(agent.dir, "theirs.md", extra=f"project: github.com/x/other\nrefs:\n- github.com/x/other:docs/a.md@deadbee\ncheck: touch {marker}\n")
    fm = engrams.page_frontmatter("theirs.md", agent)
    assert engrams.suspicion(fm, run_checks=True) == []
    engrams.main(["doubt"])
    assert "not checked here" in capsys.readouterr().err and not marker.exists()
    engrams.main(["verify", "agent/theirs.md"])
    assert "verified agent/theirs.md" in capsys.readouterr().out and not marker.exists()
    assert engrams.page_frontmatter("theirs.md", agent)["refs"] == ["github.com/x/other:docs/a.md@deadbee"]


def test_verify_keeps_other_project_refs(tmp_path, monkeypatch):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    pid = engrams.project_id()
    old = _git(proj, "log", "-1", "--format=%h").strip()
    (proj / "docs" / "a.md").write_text("changed\n"); _git(proj, "commit", "-qam", "change")
    new = _git(proj, "log", "-1", "--format=%h").strip()
    _page(agent.dir, "mixed.md", extra=f"project: {pid}\nrefs:\n- {pid}:docs/a.md@{old}\n- github.com/x/other:lib/b.py@abc1234\n")
    engrams.main(["verify", "mixed.md"])
    assert engrams.page_frontmatter("mixed.md", agent)["refs"] == [f"{pid}:docs/a.md@{new}", "github.com/x/other:lib/b.py@abc1234"]


def test_search_ranks_current_project_first(tmp_path, monkeypatch, capsys):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    engrams.write_config_file({"semantic": False})
    pid = engrams.project_id()
    _page(agent.dir, "aaa-elsewhere.md", "zeppelin notes", extra="project: github.com/x/other\n")
    _page(agent.dir, "zzz-here.md", "zeppelin notes", extra=f"project: {pid}\n")
    engrams.main(["search", "zeppelin"])
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in lines] == ["agent/zzz-here.md", "agent/aaa-elsewhere.md"]


def test_doctor_warns_about_non_page_md(tmp_path, monkeypatch):
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    (agent.dir / "README.md").write_text("# engrams repo\n")
    assert engrams.non_pages(agent) == ["README.md"]


def test_guard_denies_a_raw_read_in_a_remote_store():
    import subprocess
    shim = ROOT / "scripts" / "guard.sh"
    def run(payload):
        return subprocess.run(["sh", str(shim)], input=json.dumps(payload), capture_output=True, text=True).stdout
    page = "/home/u/.local/share/dokidlc-engrams/stores/agent-3f9c2a10/a-page.md"
    for payload in ({"tool_name": "Bash", "tool_input": {"command": f"cat {page}"}}, {"tool_name": "Read", "tool_input": {"file_path": page}}):
        out = json.loads(run(payload))
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "engrams read STORE/a-page.md" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert run({"tool_name": "Read", "tool_input": {"file_path": page.replace("a-page.md", "index.md")}}) == ""


def test_load_stores_rejects_two_project_stores(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "engrams.toml").write_text('[stores.project]\nkind = "project"\n[stores.second]\nkind = "project"\npath = "m2"\n')
    with pytest.raises(engrams.ConfigError) as e:
        engrams.load_stores(tmp_path)
    assert "at most one project store" in str(e.value)


def test_brief_starts_a_background_index_after_a_pull(tmp_path, monkeypatch, capsys):
    """The hook returns within its budget, and the reindex runs detached in its own session."""
    import io, os, time
    proj, agent, bare = _remote(tmp_path, monkeypatch)
    engrams.write_config_file({"semantic": False})
    procs = []
    real = engrams.start_background
    asked = []
    monkeypatch.setattr(engrams, "start_background", lambda argv: asked.append(argv) or procs.append(real(["sleep", "3"])))
    _push_page(_other_clone(tmp_path, bare), "theirs.md")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart", "source": "startup"})))
    t0 = time.monotonic()
    engrams.main(["doctor", "--brief", "--hook"])
    assert time.monotonic() - t0 < engrams.BRIEF_PULL_BUDGET + 2      # did not wait for the 3 s child
    p = procs[0]
    try:
        assert p.poll() is None and os.getsid(p.pid) != os.getsid(0)   # still running, in its own session
    finally:
        p.kill()
    assert "Pulled 1 page" in capsys.readouterr().out and asked[0][-1] == "index"


def test_brief_names_doctor_fix_when_only_a_remote_store_is_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path)); monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st")); monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    engrams.write_config_file({"semantic": False})
    (tmp_path / ".claude").mkdir(); (tmp_path / ".claude" / "engrams.toml").write_text('[stores.agent]\nkind = "remote"\nurl = "u"\n')
    engrams.main(["doctor", "--brief"])
    assert "engrams doctor --fix" in capsys.readouterr().out


def test_last_line_prefers_git_fatal_line():
    import subprocess
    p = subprocess.CompletedProcess([], 128, "", "fatal: '/x/remote.git' does not appear to be a git repository\nfatal: Could not read from remote repository.\n\nPlease make sure you have the correct access rights\nand the repository exists.\n")
    assert engrams.last_line(p) == "fatal: '/x/remote.git' does not appear to be a git repository"
    assert engrams.last_line(subprocess.CompletedProcess([], 1, "", "")) == "git exited 1"


# --- refs fire on cited content ------------------------------------------------


def _cited(tmp_path, monkeypatch, body="intro\n\n## Alpha\n\nalpha text\n\n## Beta\n\nbeta text\n"):
    """A project with docs/doc.md committed; returns its short sha."""
    _project(tmp_path, monkeypatch)
    (tmp_path / "docs" / "doc.md").write_text(body)
    _git(tmp_path, "add", "docs/doc.md"); _git(tmp_path, "commit", "-qm", "doc")
    return _git(tmp_path, "log", "-1", "--format=%h").strip()


def test_ref_follows_a_rename(tmp_path, monkeypatch, capsys):
    sha = _cited(tmp_path, monkeypatch)
    _page(tmp_path / ".engrams", "cites.md", extra=f"refs:\n- docs/doc.md@{sha}\n")
    _git(tmp_path, "mv", "docs/doc.md", "docs/moved.md"); _git(tmp_path, "commit", "-qm", "move")
    fm = engrams.page_frontmatter("cites.md")
    assert engrams.suspicion(fm) == []
    engrams.main(["verify", "cites.md"])
    assert engrams.page_frontmatter("cites.md")["refs"][0].startswith("docs/moved.md@")


def test_ref_changed_then_reverted_is_clean(tmp_path, monkeypatch):
    sha = _cited(tmp_path, monkeypatch)
    doc = tmp_path / "docs" / "doc.md"
    original = doc.read_text()
    doc.write_text(original + "edit\n"); _git(tmp_path, "commit", "-qam", "edit")
    assert engrams.ref_changed(f"docs/doc.md@{sha}", tmp_path)
    doc.write_text(original); _git(tmp_path, "commit", "-qam", "revert")
    assert engrams.ref_changed(f"docs/doc.md@{sha}", tmp_path) is None


SECTIONED = "intro\n\n## Alpha\n\nalpha text\n\n```\n## Gamma in a fence\n```\n\nalpha after the fence\n\n## Beta\n\nbeta text\n"


def test_section_ref_ignores_edits_elsewhere(tmp_path, monkeypatch):
    sha = _cited(tmp_path, monkeypatch, SECTIONED)
    doc = tmp_path / "docs" / "doc.md"
    doc.write_text(SECTIONED.replace("beta text", "beta rewritten")); _git(tmp_path, "commit", "-qam", "beta")
    assert engrams.ref_changed(f"docs/doc.md#Alpha@{sha}", tmp_path) is None
    assert engrams.ref_changed(f"docs/doc.md@{sha}", tmp_path)          # the whole file did change


def test_section_ref_fires_on_its_own_text(tmp_path, monkeypatch):
    sha = _cited(tmp_path, monkeypatch, SECTIONED)
    doc = tmp_path / "docs" / "doc.md"
    doc.write_text(SECTIONED.replace("alpha after the fence", "alpha changed after the fence")); _git(tmp_path, "commit", "-qam", "alpha")
    reason = engrams.ref_changed(f"docs/doc.md#Alpha@{sha}", tmp_path)
    assert reason and "docs/doc.md#Alpha changed since cited" in reason


def test_section_ref_missing_heading_is_suspect(tmp_path, monkeypatch):
    sha = _cited(tmp_path, monkeypatch, SECTIONED)
    doc = tmp_path / "docs" / "doc.md"
    doc.write_text(SECTIONED.replace("## Beta", "## Renamed")); _git(tmp_path, "commit", "-qam", "rename heading")
    assert "section no longer exists" in engrams.ref_changed(f"docs/doc.md#Beta@{sha}", tmp_path)


def test_section_ref_heading_with_a_colon(tmp_path, monkeypatch):
    body = "## Review record: plan\n\nfirst\n\n## Other\n\nx\n"
    sha = _cited(tmp_path, monkeypatch, body)
    _page(tmp_path / ".engrams", "colon.md", extra=f"refs:\n- 'docs/doc.md#Review record: plan@{sha}'\n")
    (tmp_path / "docs" / "doc.md").write_text(body.replace("first", "second")); _git(tmp_path, "commit", "-qam", "edit")
    signals = engrams.suspicion(engrams.page_frontmatter("colon.md"))
    assert [s for s, _ in signals] == ["ref"] and "Review record: plan" in signals[0][1]


def test_verify_moves_a_section_ref(tmp_path, monkeypatch):
    sha = _cited(tmp_path, monkeypatch, SECTIONED)
    _page(tmp_path / ".engrams", "sect.md", extra=f"refs:\n- docs/doc.md#Alpha@{sha}\n")
    _git(tmp_path, "mv", "docs/doc.md", "docs/moved.md"); _git(tmp_path, "commit", "-qm", "move")
    assert engrams.suspicion(engrams.page_frontmatter("sect.md")) == []
    engrams.main(["verify", "sect.md"])
    ref = engrams.page_frontmatter("sect.md")["refs"][0]
    assert ref.startswith("docs/moved.md#Alpha@") and not ref.endswith(sha)


def test_write_section_ref_fills_and_refuses_a_missing_heading(tmp_path, monkeypatch, capsys):
    sha = _cited(tmp_path, monkeypatch, SECTIONED)
    _write(monkeypatch, "with-section.md", "--ref", "docs/doc.md#Beta")
    assert engrams.page_frontmatter("with-section.md")["refs"] == [f"docs/doc.md#Beta@{sha}"]
    with pytest.raises(SystemExit):
        _write(monkeypatch, "bad-section.md", "--ref", "docs/doc.md#Nope")
    assert "no heading 'Nope'" in capsys.readouterr().err


def test_whole_file_ref_needs_a_hex_sha(tmp_path, monkeypatch):
    _cited(tmp_path, monkeypatch)
    for bad in ("docs/doc.md@HEAD", "docs/doc.md@HEAD~1", "docs/doc.md@zzzzzzz"):
        assert "cited sha is not hex" in engrams.ref_changed(bad, tmp_path), bad


def test_names_are_engrams(tmp_path, monkeypatch):
    assert engrams.STORE_CONFIG == ".claude/engrams.toml"
    assert engrams.CLAUDE_MD_MARK == "<!-- engrams -->"
    stores, _ = engrams.load_stores(tmp_path)
    assert stores[0].dir == tmp_path / ".engrams"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "c")); monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "d")); monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "s"))
    assert [engrams.config_file().parent.name, engrams.data_dir().name, engrams.state_dir().name] == ["dokidlc-engrams"] * 3


MIGRATION_LINE = "engrams: this repository or machine still uses the memory plugin's layout."


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
    engrams.main(argv)
    return capsys.readouterr().out


def test_doctor_brief_offers_migration(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    repo = tmp_path / "repo"; repo.mkdir(); _old_layout(repo)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    for argv in (["doctor", "--brief"], ["doctor", "--brief", "--hook"]):
        assert MIGRATION_LINE in _brief(argv, monkeypatch, capsys)
    machine = tmp_path / "machine"; machine.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(machine))
    (Path(engrams.os.environ["XDG_DATA_HOME"]) / "dokidlc-memory").mkdir(parents=True)
    for argv in (["doctor", "--brief"], ["doctor", "--brief", "--hook"]):
        assert MIGRATION_LINE in _brief(argv, monkeypatch, capsys)


def test_migrate_fixture(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    repo = tmp_path / "repo"; repo.mkdir(); _repo(repo); _old_layout(repo)
    (repo / ".claude" / "settings.local.json").write_text(json.dumps({"enabledPlugins": {"memory@memory-dev": True}}) + "\n")
    _git(repo, "add", "."); _git(repo, "commit", "-qm", "old layout")
    bases = [Path(engrams.os.environ[v]) for v in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME")]
    for b in bases:
        (b / "dokidlc-memory").mkdir(parents=True); (b / "dokidlc-memory" / "kept.txt").write_text("x\n")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    reindexed = []
    monkeypatch.setattr(engrams, "reindex", lambda: reindexed.append(1))
    commits = _git(repo, "rev-list", "--count", "HEAD")
    assert MIGRATION_LINE in _brief(["doctor", "--brief"], monkeypatch, capsys)

    engrams.main(["migrate"])
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1] == 'Suggested commit: git commit -m "engrams: migrate from the memory plugin"'
    assert any("settings.local.json" in line and "memory@memory-dev" in line for line in out)
    assert not (repo / ".memory").exists() and sorted(p.name for p in (repo / ".engrams").iterdir()) == ["a-page.md", "index.md"]
    assert not (repo / ".claude" / "memory.toml").exists()
    assert 'path = ".engrams"' in (repo / ".claude" / "engrams.toml").read_text()
    claude_md = (repo / "CLAUDE.md").read_text()
    assert "## Engrams <!-- engrams -->" in claude_md and "<!-- memory -->" not in claude_md and "## Other\n\nKept." in claude_md
    settings = json.loads((repo / ".claude" / "settings.json").read_text())["enabledPlugins"]
    assert settings == {"engrams@dokidlc": True, "questlog@dokidlc": True}
    assert "memory@memory-dev" in (repo / ".claude" / "settings.local.json").read_text()
    page = (repo / ".engrams" / "a-page.md").read_text()
    assert "`engrams read b.md`" in page and "`engrams doctor --fix`" in page and "memory as a word stays" in page
    assert "engrams format" in (repo / ".engrams" / "index.md").read_text() and reindexed
    for b in bases:
        assert not (b / "dokidlc-memory").exists() and (b / "dokidlc-engrams" / "kept.txt").is_file()
    assert _git(repo, "rev-list", "--count", "HEAD") == commits
    assert ".engrams/a-page.md" in _git(repo, "diff", "--cached", "--name-only")

    engrams.main(["migrate"])
    assert capsys.readouterr().out.strip() == "nothing to migrate"
    assert MIGRATION_LINE not in _brief(["doctor", "--brief"], monkeypatch, capsys)


def test_docs_name_engrams():
    """The skill and the docs a reader acts on name engrams; only lines about the migration keep the old names."""
    docs = [ROOT / "skills" / "engrams" / "SKILL.md", *sorted((ROOT / "skills" / "engrams" / "references").glob("*.md")),
            ROOT / "README.md", ROOT / "INSTALL.md", ROOT / "DEVELOPMENT.md"]
    old = re.compile(r"`memory [a-z]|\.memory/|memory\.toml|bin/memory|memory@")
    hits = [f"{d.relative_to(ROOT)}:{n}" for d in docs if d.is_file() for n, line in enumerate(d.read_text().splitlines(), 1)
            if old.search(line) and "migrat" not in line]
    assert (ROOT / "skills" / "engrams" / "SKILL.md").is_file() and hits == []
