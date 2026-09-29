#!/bin/bash
# Pins the two things that break silently: the shape of opencode's message
# table, and the percentage scale coming off opencode.ai.
#
# Both are checked against a throwaway fixture rather than the real database, so
# a developer's own usage never decides whether the suite passes.

set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COLLECTOR="$ROOT/bin/opencode-go-watcher-usage"
FIXTURE="$(mktemp -d)"
trap 'rm -rf "$FIXTURE"' EXIT

pass_count=0
fail_count=0

pass() {
  pass_count=$((pass_count + 1))
  echo "  ok   $1"
}

fail() {
  fail_count=$((fail_count + 1))
  echo "  FAIL $1"
  echo "       got: $2" | head -20
}

check() {
  local label="$1" expected="$2" actual="$3"
  if [[ $expected == "$actual" ]]; then
    pass "$label"
  else
    fail "$label" "expected [$expected], got [$actual]"
  fi
}

run_collector() {
  local home="$1"
  shift
  HOME="$home" XDG_DATA_HOME="$home/.local/share" XDG_CACHE_HOME="$home/.cache" \
    OPENCODE_API_KEY='' "$COLLECTOR" "$@" 2>/dev/null
}

# Builds an opencode-shaped message table. The columns mirror the real schema
# closely enough that a column rename upstream shows up here.
build_db() {
  local db="$1"
  mkdir -p "$(dirname "$db")"
  python3 - "$db" <<'PY'
import json
import sqlite3
import sys
import time
from pathlib import Path

db = Path(sys.argv[1])
conn = sqlite3.connect(db)
conn.execute(
    "CREATE TABLE message (id text PRIMARY KEY, session_id text NOT NULL,"
    " time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL)"
)
now_ms = int(time.time() * 1000)


def row(rid, session, provider, model, role="assistant", inp=0, out=0, reasoning=0, read=0, write=0, raw=None):
  payload = raw if raw is not None else {
      "role": role,
      "providerID": provider,
      "modelID": model,
      "tokens": {"input": inp, "output": out, "reasoning": reasoning, "cache": {"read": read, "write": write}},
      "time": {"created": now_ms},
  }
  return (rid, session, now_ms, now_ms, payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":")))


rows = [
    # The one row that must count: 80 in + 40 out + 5 reasoning + 30 cache read.
    row("m1", "s1", "opencode-go", "kimi-k2.6", inp=80, out=40, reasoning=5, read=30),
    # Must not count: other subscriptions, a user turn, a prefix-colliding
    # gateway, and an assistant turn that burned no tokens.
    row("m2", "s1", "anthropic", "claude-opus-5", inp=999, out=999),
    row("m3", "s1", "opencode", "space-bunny-free", inp=999, out=999),
    row("m4", "s1", "opencode-go-proxy", "kimi-k2.6", inp=999, out=999),
    row("m5", "s1", "opencode-go", "kimi-k2.6", role="user", inp=999, out=999),
    row("m6", "s1", "opencode-go", "kimi-k2.6"),
    # A second session, so session counting is not accidentally a message count.
    row("m7", "s2", "opencode-go", "kimi-k2.6", inp=10, out=0),
    # A third counting row, back in the first session: three prompts, two
    # sessions. m8 and m9 below are corrupt and must not be counted at all.
    row("m10", "s1", "opencode-go", "kimi-k2.6", inp=5, out=0),
    # Malformed rows: trailing garbage after valid JSON, and not JSON at all.
    # A single bad row must not abort the scan.
    row("m8", "s2", "opencode-go", "kimi-k2.6", raw=json.dumps({
        "role": "assistant", "providerID": "opencode-go", "modelID": "kimi-k2.6",
        "tokens": {"input": 999, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}},
        "time": {"created": now_ms}}) + " trailing-garbage"),
    row("m9", "s2", "opencode-go", "kimi-k2.6", raw="this is not json"),
]
conn.executemany("INSERT INTO message VALUES (?, ?, ?, ?, ?)", rows)
conn.commit()
conn.close()
PY
}

echo "collector: no database, no key"
empty_home="$FIXTURE/empty"
record=$(run_collector "$empty_home")
check "prints a valid record" "opencode-go" "$(jq -r '.id' <<<"$record" 2>/dev/null)"
check "stays hidden with no data" "false" "$(jq -r '.ready' <<<"$record" 2>/dev/null)"
check "reports no local stats" "false" "$(jq -r '.hasLocalStats' <<<"$record" 2>/dev/null)"
check "offers no auth hint without a key" "" "$(jq -r '.authHelpText' <<<"$record" 2>/dev/null)"

echo "collector: opencode-go messages only"
db_home="$FIXTURE/db"
build_db "$db_home/.local/share/opencode/opencode.db"
record=$(run_collector "$db_home" --force)
check "counts reasoning into output" "45" "$(jq -r '.modelUsage["kimi-k2.6"].outputTokens' <<<"$record")"
check "counts input" "95" "$(jq -r '.modelUsage["kimi-k2.6"].inputTokens' <<<"$record")"
check "keeps cache read separate" "30" "$(jq -r '.modelUsage["kimi-k2.6"].cacheReadInputTokens' <<<"$record")"
check "sums today" "170" "$(jq -r '.todayTotalTokens' <<<"$record")"
check "counts three prompts" "3" "$(jq -r '.totalPrompts' <<<"$record")"
check "counts two sessions, not three prompts" "2" "$(jq -r '.totalSessions' <<<"$record")"
check "reports local stats" "true" "$(jq -r '.hasLocalStats' <<<"$record")"
check "always emits seven days" "7" "$(jq -r '.recentDays | length' <<<"$record")"

echo "collector: scan cache"
cache_home="$FIXTURE/cache"
build_db "$cache_home/.local/share/opencode/opencode.db"
run_collector "$cache_home" >/dev/null
check "a fresh scan is cached" "170" "$(jq -r '.todayTotalTokens' <<<"$(run_collector "$cache_home" --limits-only)")"

python3 - "$cache_home/.local/share/opencode/opencode.db" <<'PY'
import json
import sqlite3
import sys
import time

conn = sqlite3.connect(sys.argv[1])
now_ms = int(time.time() * 1000)
conn.execute("INSERT INTO message VALUES (?, ?, ?, ?, ?)", (
    "late", "s1", now_ms, now_ms, json.dumps({
        "role": "assistant", "providerID": "opencode-go", "modelID": "kimi-k2.6",
        "tokens": {"input": 35, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}},
        "time": {"created": now_ms}}, separators=(",", ":"))))
conn.commit()
conn.close()
PY
check "--limits-only reuses the cached scan" "170" "$(jq -r '.todayTotalTokens' <<<"$(run_collector "$cache_home" --limits-only)")"
check "--force rescans past the cache" "205" "$(jq -r '.todayTotalTokens' <<<"$(run_collector "$cache_home" --force)")"

echo "collector: usage endpoint, with the network stubbed"
if ! python3 - "$COLLECTOR" "$FIXTURE" <<'PY'
import importlib.machinery
import importlib.util
import json
import os
import sys
import urllib.error
from pathlib import Path

loader = importlib.machinery.SourceFileLoader("watcher", sys.argv[1])
spec = importlib.util.spec_from_loader(loader.name, loader)
watcher = importlib.util.module_from_spec(spec)
loader.exec_module(watcher)


class FakeResponse:
  def __init__(self, payload):
    self.payload = payload

  def read(self):
    return json.dumps(self.payload).encode("utf-8")

  def __enter__(self):
    return self

  def __exit__(self, *args):
    return False


def respond(payload):
  return lambda *a, **k: FakeResponse(payload)


def http_error(code):
  def raiser(*a, **k):
    raise urllib.error.HTTPError("http://stub", code, "{}", {}, None)
  return raiser


os.environ["XDG_CACHE_HOME"] = str(Path(sys.argv[2]) / "limits-cache")

# percent arrives as 0..100 and must leave as 0..1. A value of exactly 1 is one
# percent, not one hundred.
watcher.urllib.request.urlopen = respond({"usage": {
    "rolling": {"status": "ok", "percent": 1, "resetsAt": "2026-08-16T06:00:00Z"},
    "weekly": {"status": "ok", "percent": 50, "resetsAt": "2026-08-17T00:00:00+00:00"},
    "monthly": {"status": "rate-limited", "percent": 100, "resetsAt": "2026-08-28T00:00:00Z"},
}})
limits, status, help_text, retry = watcher.fetch_limits("sk-test", "https://stub")
assert [w["label"] for w in limits] == ["Rolling (5-hour)", "Weekly (7-day)", "Monthly (30-day)"], limits
assert [w["percent"] for w in limits] == [0.01, 0.5, 1.0], limits
assert limits[0]["resetsAt"] == "2026-08-16T06:00:00+00:00", limits[0]
assert status == "" and help_text == "" and retry is False

# A 200 carrying no usage object is no limits, not a crash.
for payload in ({}, {"usage": None}, {"usage": ["rolling"]}, {"error": "no subscription"}):
  watcher.urllib.request.urlopen = respond(payload)
  limits, _, help_text, _ = watcher.fetch_limits("sk-test", "https://stub")
  assert limits == [] and help_text == "No usage data returned for this key.", (payload, limits, help_text)

# A window with no reset time keeps its meter; the panel just drops the countdown.
watcher.urllib.request.urlopen = respond({"usage": {"rolling": {"status": "ok", "percent": 93}}})
limits, _, _, _ = watcher.fetch_limits("sk-test", "https://stub")
assert limits == [{"label": "Rolling (5-hour)", "percent": 0.93, "resetsAt": ""}], limits

# Auth failures get stable help text and never reuse stale limits.
watcher.urllib.request.urlopen = http_error(401)
assert watcher.fetch_limits("sk-test", "https://stub")[2] == "opencode.ai rejected the API key."
watcher.urllib.request.urlopen = http_error(403)
assert watcher.fetch_limits("sk-test", "https://stub")[2] == "This key has no OpenCode Go subscription."

# The key must never travel over a non-HTTPS endpoint.
watcher.urllib.request.urlopen = respond({"usage": {"rolling": {"percent": 10}}})
limits, status, help_text, retry = watcher.fetch_limits("sk-test", "http://insecure")
assert limits == [] and retry is False and "HTTPS" in help_text, (limits, help_text)

# Transient failures fall back to the cache, but only while a window could
# still be true: a cached window whose reset time has passed is dropped.
watcher.urllib.request.urlopen = respond({"usage": {
    "rolling": {"status": "ok", "percent": 10, "resetsAt": "2999-01-01T00:00:00Z"},
    "weekly": {"status": "ok", "percent": 20, "resetsAt": "2000-01-01T00:00:00Z"},
}})
watcher.write_limits_cache(watcher.fetch_limits("sk-test", "https://stub")[0])
watcher.urllib.request.urlopen = http_error(503)
limits, status, help_text, retry = watcher.fetch_limits("sk-test", "https://stub")
assert [w["label"] for w in limits] == ["Rolling (5-hour)"], limits
assert status == "OpenCode Go limits stale" and retry is True, (status, retry)

watcher.urllib.request.urlopen = http_error(429)
assert watcher.fetch_limits("sk-test", "https://stub")[3] is True


def url_error(*a, **k):
  raise urllib.error.URLError("network down")


watcher.urllib.request.urlopen = url_error
assert watcher.fetch_limits("sk-test", "https://stub")[3] is True

# OPENCODE_API_KEY wins over opencode's own auth.json.
os.environ["XDG_DATA_HOME"] = str(Path(sys.argv[2]) / "auth")
auth = Path(sys.argv[2]) / "auth" / "opencode" / "auth.json"
auth.parent.mkdir(parents=True, exist_ok=True)
auth.write_text(json.dumps({"opencode-go": {"key": "sk-from-auth-file"}}))
os.environ["OPENCODE_API_KEY"] = "sk-from-env"
assert watcher.api_key() == "sk-from-env"
os.environ.pop("OPENCODE_API_KEY")
assert watcher.api_key() == "sk-from-auth-file"
PY
then
  fail "usage endpoint handling" "see the assertion above"
else
  pass "scales percent, maps auth failures, and expires the stale-limits cache"
fi

echo
echo "$pass_count passed, $fail_count failed"
[[ $fail_count -eq 0 ]]
