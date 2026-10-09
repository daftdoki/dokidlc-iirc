#!/bin/sh
# Builds the three fixture repositories the iirc skill evals run in.
# Each is a git repo with a .iirc/ field written through the plugin copy,
# so pages carry real embeddings, refs, and commit stamps.
# Run through setup.sh, which sets IIRC_EVAL_WORKSPACE and builds the plugin copies first.
set -eu
W=${IIRC_EVAL_WORKSPACE:?run setup.sh}
PLUGIN=$W/plugin-live
export PATH="$PLUGIN/bin:$(echo "$PATH" | tr ':' '\n' | grep -v '/.claude/plugins/cache/' | paste -sd: -)"
export XDG_STATE_HOME=$W/build-state
REPOS=$W/repos
rm -rf "$REPOS" "$XDG_STATE_HOME"
mkdir -p "$REPOS"

newrepo() {
  mkdir -p "$REPOS/$1" && cd "$REPOS/$1"
  git init -q && git config user.email fixture@test && git config user.name fixture
  printf '__pycache__/\n*.pyc\n.DS_Store\n' > .gitignore
  mkdir -p .claude
  printf '{\n  "enabledPlugins": {"iirc@dokidlc": true}\n}\n' > .claude/settings.json
}

commit() { git add -A && git commit -qm "$1"; }

page() {  # page NAME TITLE SUMMARY TOPICS KIND [extra iirc write args...]; body on stdin
  n=$1; t=$2; s=$3; tp=$4; k=$5; shift 5
  iirc write "$n" --title "$t" --summary "$s" --topics "$tp" --kind "$k" "$@"
}

# ---------------------------------------------------------------- ledger ----
# eval 1 (search before debug) and eval 4 (remember a fact a file holds)
newrepo ledger
cat > README.md <<'EOF'
# ledger

A small double-entry ledger used to check month-end reports.

Run the tests with `make test`.
EOF
cat > Makefile <<'EOF'
.PHONY: test db clean

test:
	python3 -m unittest discover -s tests -q

# The fixture database is not committed. Build it from the seed before the tests.
db:
	python3 scripts/build_db.py

clean:
	rm -f tests/fixtures/sample.db
EOF
mkdir -p src/ledger tests/fixtures scripts
cat > src/ledger/__init__.py <<'EOF'
EOF
cat > src/ledger/report.py <<'EOF'
"""Month-end totals from the entries table."""
import sqlite3
from pathlib import Path


def totals(db_path: Path) -> dict[str, int]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute("SELECT account, SUM(cents) FROM entries GROUP BY account").fetchall()
    finally:
        con.close()
    return {account: cents for account, cents in rows}


def balanced(db_path: Path) -> bool:
    return sum(totals(db_path).values()) == 0
EOF
cat > tests/fixtures/seed.sql <<'EOF'
CREATE TABLE entries (id INTEGER PRIMARY KEY, account TEXT NOT NULL, cents INTEGER NOT NULL);
INSERT INTO entries (account, cents) VALUES ('cash', -1200), ('rent', 1200), ('cash', -300), ('food', 300);
EOF
cat > scripts/build_db.py <<'EOF'
"""Build tests/fixtures/sample.db from seed.sql. The database is not committed."""
import sqlite3
from pathlib import Path

root = Path(__file__).resolve().parents[1]
db = root / "tests" / "fixtures" / "sample.db"
db.unlink(missing_ok=True)
con = sqlite3.connect(db)
con.executescript((root / "tests" / "fixtures" / "seed.sql").read_text())
con.commit()
con.close()
print(f"built {db.relative_to(root)}")
EOF
cat > tests/test_report.py <<'EOF'
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ledger.report import balanced, totals  # noqa: E402

DB = ROOT / "tests" / "fixtures" / "sample.db"


class ReportTest(unittest.TestCase):
    def test_totals_by_account(self):
        self.assertEqual(totals(DB), {"cash": -1500, "rent": 1200, "food": 300})

    def test_books_balance(self):
        self.assertTrue(balanced(DB))
EOF
printf 'tests/fixtures/sample.db\n' >> .gitignore
commit "ledger: report, tests, seed"
iirc init >/dev/null
commit "iirc init"
page ledger-tests-need-make-db.md \
  "The ledger tests fail with 'no such table: entries' until make db has run" \
  "sqlite creates an empty sample.db on connect, so the error is a missing table, not a missing file; run make db first" \
  "ledger,tests" procedure --ref Makefile <<'EOF'
`make test` on a fresh clone fails both tests with `sqlite3.OperationalError: no such table: entries`. The database `tests/fixtures/sample.db` is gitignored and sqlite creates an empty one on the first connect, so the error names a table, not a file. Run `make db` once; it builds the database from `tests/fixtures/seed.sql`. `make clean` removes it.

Took two attempts on 2026-09-14: the first read of the error sent me into the report module looking for a wrong table name.

## Sources

- `make test` and `make db` in this repository, 2026-09-14
- Makefile, `db` target
EOF
page ledger-ci-runs-on-ubuntu-2204.md \
  "CI for ledger runs on ubuntu-22.04 with the system sqlite" \
  "The CI image's sqlite is 3.37; window functions newer than that fail only there" \
  "ledger,ci" environment <<'EOF'
The GitHub workflow pins `ubuntu-22.04`, whose sqlite is 3.37.2. A query that used `GROUP_CONCAT(... ORDER BY)` passed on the Mac (sqlite 3.45) and failed in CI on 2026-09-10. Test against 3.37 syntax.

## Sources

- CI run for commit 4b1c2e0, 2026-09-10
EOF
page creator-prefers-unittest-over-pytest.md \
  "The creator chose unittest over pytest for the ledger tests" \
  "No third-party test runner: the project has no dependencies and the creator wants it to stay that way" \
  "ledger,decisions" decision <<'EOF'
On 2026-09-08 the creator declined a pytest migration. The reason: the ledger has no dependencies and `python3 -m unittest` runs on a bare interpreter. Do not add pytest, fixtures plugins, or a dev-requirements file.

## Sources

- Conversation with the creator, 2026-09-08
EOF
page ruff-config-lives-in-pyproject.md \
  "Lint with ruff; its config is the [tool.ruff] table in pyproject.toml" \
  "Line length 100, E and F rules only; run ruff check src tests" \
  "ledger,lint" procedure <<'EOF'
`ruff check src tests` is the lint command. The config is `[tool.ruff]` in `pyproject.toml`: line length 100, rule sets E and F. There is no pre-commit hook.

## Sources

- pyproject.toml, read 2026-09-09
EOF
commit "iirc: four pages"
cd "$W"

# ------------------------------------------------------------ syncproj ----
# eval 2 (write after learning): a script that fails twice for two reasons
newrepo syncproj
cat > README.md <<'EOF'
# syncproj

Pulls the shared record set into `.sync/state.json` for local tooling.

    python3 scripts/sync.py

See docs/sync.md.
EOF
mkdir -p docs scripts .sync
cat > docs/sync.md <<'EOF'
# sync

`scripts/sync.py` pulls records from the shared store into `.sync/state.json`.
It refuses to run while another sync holds the lock. It takes a profile from
the `SYNC_PROFILE` environment variable. The store address for each profile is
in `scripts/profiles.json`.
EOF
cat > scripts/profiles.json <<'EOF'
{
  "remote": {"store": "store.internal.example:7433", "route": "vpn"},
  "local": {"store": "127.0.0.1:7433", "route": "loopback"}
}
EOF
cat > scripts/sync.py <<'EOF'
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / ".sync" / "lock"
STATE = ROOT / ".sync" / "state.json"
PROFILES = json.loads((ROOT / "scripts" / "profiles.json").read_text())


def fail(code: str, msg: str, status: int) -> None:
    print(f"sync: {code}: {msg}", file=sys.stderr)
    sys.exit(status)


def route_up(route: str) -> bool:
    if route == "loopback":
        return True
    return os.environ.get("SYNC_ROUTE_" + route.upper()) == "up"


def main() -> None:
    if LOCK.exists():
        held = LOCK.read_text().strip()
        fail("E_LOCK", f"lock held by {held}", 3)
    profile = os.environ.get("SYNC_PROFILE", "remote")
    if profile not in PROFILES:
        fail("E_PROFILE", f"unknown profile {profile!r}", 2)
    p = PROFILES[profile]
    if not route_up(p["route"]):
        fail("E_NOROUTE", f"0x1a {p['store']}", 4)
    LOCK.parent.mkdir(exist_ok=True)
    LOCK.write_text(f"pid {os.getpid()} since {time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime())}\n")
    try:
        records = [{"id": i, "store": p["store"]} for i in range(12)]
        STATE.write_text(json.dumps({"profile": profile, "records": records}, indent=1) + "\n")
        print(f"sync: {len(records)} records synced to {STATE.relative_to(ROOT)}")
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
EOF
printf '.sync/\n' >> .gitignore
printf 'pid 48213 since 2026-09-18T07:12Z\n' > .sync/lock
commit "syncproj: sync script, docs, profiles"
iirc init >/dev/null
commit "iirc init"
page syncproj-state-json-is-read-by-the-report-tool.md \
  "The report tool reads .sync/state.json and expects a records list" \
  "Do not change the state.json shape without updating tools/report.py in the reports repo" \
  "syncproj,decisions" decision <<'EOF'
The reports repository's `tools/report.py` reads `.sync/state.json` and indexes `records` by `id`. The creator decided on 2026-09-12 that the sync script owns that shape and the report tool follows it, so a shape change is announced in the reports repository first.

## Sources

- Conversation with the creator, 2026-09-12
EOF
page syncproj-store-port-7433.md \
  "The shared store listens on 7433 for both profiles" \
  "Both profiles in scripts/profiles.json use port 7433; the host differs" \
  "syncproj,environment" environment --ref scripts/profiles.json <<'EOF'
`scripts/profiles.json` gives the store address per profile. Both use port 7433. The remote host is `store.internal.example`, the local one is loopback.

## Sources

- scripts/profiles.json, read 2026-09-15
EOF
commit "iirc: two pages"
cd "$W"

# ----------------------------------------------------------- devserver ----
# eval 3 (a suspect page): the cited file changed after the page was written
newrepo devserver
cat > README.md <<'EOF'
# devserver

A tiny HTTP service for local development of the dashboard. See docs/config.md.
EOF
mkdir -p docs server scripts
cat > docs/config.md <<'EOF'
# Dev server configuration

The dev server binds to `127.0.0.1` on port **8080**. Health is served at
`/healthz` and returns `ok` with status 200.

Settings live in `server/settings.py`.
EOF
cat > server/settings.py <<'EOF'
HOST = "127.0.0.1"
PORT = 8080
HEALTH_PATH = "/healthz"
EOF
cat > server/app.py <<'EOF'
from http.server import BaseHTTPRequestHandler, HTTPServer

from settings import HEALTH_PATH, HOST, PORT


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == HEALTH_PATH:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok\n")
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    HTTPServer((HOST, PORT), Handler).serve_forever()
EOF
commit "devserver: app, settings, docs"
iirc init >/dev/null
commit "iirc init"
page dev-server-port.md \
  "The dev server listens on 127.0.0.1:8080 and answers /healthz" \
  "Port 8080, health at /healthz returns ok; see docs/config.md" \
  "devserver,environment" environment --ref docs/config.md <<'EOF'
The dev server binds to `127.0.0.1:8080`. `GET /healthz` returns `ok` with status 200. Port and path are constants in `server/settings.py`, documented in `docs/config.md`.

## Sources

- docs/config.md, read 2026-09-11
- `python3 server/app.py` then `curl -s http://127.0.0.1:8080/healthz`, 2026-09-11
EOF
page devserver-run-from-server-dir.md \
  "Run the dev server from inside server/ or the settings import fails" \
  'app.py does `from settings import ...`, so python3 server/app.py works only with server/ as cwd or on sys.path' \
  "devserver,procedure" procedure <<'EOF'
`python3 server/app.py` from the repository root works because Python puts the script's directory on `sys.path`. `python3 -m server.app` from the root does not: there is no package and `settings` is not importable. Use the first form.

## Sources

- Both commands tried on 2026-09-11
EOF
page dashboard-polls-health-every-five-seconds.md \
  "The dashboard front end polls /healthz every 5 seconds" \
  "A health endpoint slower than 5 seconds makes the dashboard flap; keep it a constant response" \
  "devserver,decisions" decision <<'EOF'
The creator set the dashboard's poll interval to 5 seconds on 2026-09-09 and asked that `/healthz` never do work: no database touch, no upstream call. A slow health check shows as flapping in the dashboard.

## Sources

- Conversation with the creator, 2026-09-09
EOF
commit "iirc: three pages"
# the change that makes dev-server-port.md suspect
sed -i '' 's/port \*\*8080\*\*/port **9090**/' docs/config.md
cat >> docs/config.md <<'EOF'

Port 8080 was given up on 2026-09-17: the corporate proxy agent on the
laptops binds it at login.
EOF
sed -i '' 's/PORT = 8080/PORT = 9090/' server/settings.py
commit "Move the dev server to 9090; 8080 clashes with the proxy agent"
cd "$W"

echo "fixtures built under $REPOS"
for r in ledger syncproj devserver; do
  (cd "$REPOS/$r" && echo "-- $r: $(git rev-parse --short HEAD)" && iirc doctor --brief </dev/null)
done
