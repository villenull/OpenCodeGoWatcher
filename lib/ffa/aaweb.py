"""Artificial Analysis numbers, read from their public website.

The free API tier returns three composite indices and nothing per evaluation,
and only some effort variants. Any model page on artificialanalysis.ai, though,
embeds a record for every model AA tracks — each effort level separately —
with its Intelligence Index, output speed and per-evaluation scores. One page
therefore gives everything the charts need, with no key and no request budget.

The records live in the page's React Server Components payload, not in an API
with a contract, so parsing is defensive: a record that doesn't parse is
skipped, and if the page can't be read at all the last good copy is used and
the window says so. Cached for a day; AA's numbers move on release days, not
hourly.
"""

from __future__ import annotations

import re
import time
import urllib.error
import urllib.request
from typing import Any

from . import store

# Any model page carries the full table; these are tried in order.
PAGES = (
  "https://artificialanalysis.ai/models/claude-opus-5-5",
  "https://artificialanalysis.ai/models",
)
CACHE_TTL_SECONDS = 24 * 60 * 60

_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', re.S)
_RECORD_START = re.compile(r'\{"id":"[0-9a-f-]{36}","slug":"')


def _payload(html: str) -> str:
  chunks = _PUSH.findall(html)
  return "".join(chunk.encode("utf-8", "ignore").decode("unicode_escape", "ignore") for chunk in chunks)


def _number(segment: str, key: str) -> float | None:
  match = re.search(r'"%s":(-?[0-9][0-9.eE+-]*)' % re.escape(key), segment)
  return float(match.group(1)) if match else None


def _string(segment: str, key: str) -> str | None:
  match = re.search(r'"%s":"([^"]*)"' % re.escape(key), segment)
  return match.group(1) if match else None


def _omniscience(segment: str) -> float | None:
  """AA-Omniscience index, -100..100. Newer models carry it in the index's
  evaluation list; older ones only as a top-level field."""
  listed = re.search(r'\{"slug":"omniscience","score":(-?[0-9.]+)', segment)
  if listed:
    return float(listed.group(1))
  return _number(segment, "omniscience")


def parse_models(html: str) -> dict[str, dict[str, Any]]:
  """slug -> {slug, name, releaseSlug, intelligence, tokensPerSecond, omniscience, deprecated}."""
  text = _payload(html)
  starts = [match.start() for match in _RECORD_START.finditer(text)]
  models: dict[str, dict[str, Any]] = {}
  for begin, end in zip(starts, starts[1:] + [len(text)]):
    segment = text[begin:end]
    slug = _string(segment, "slug")
    name = _string(segment, "name")
    if not slug or not name:
      continue
    release = re.search(r'"release":\{"slug":"([^"]+)"', segment)
    record = {
      "slug": slug,
      "name": name,
      "releaseSlug": release.group(1) if release else slug,
      "intelligence": _number(segment, "intelligenceIndex"),
      "tokensPerSecond": _number(segment, "medianOutputSpeed"),
      "omniscience": _omniscience(segment),
      "deprecated": '"deprecated":true' in segment[:4000],
    }
    # The payload can mention a model more than once; keep the fullest record.
    current = models.get(slug)
    filled = sum(value is not None for value in record.values())
    if current is None or filled > sum(value is not None for value in current.values()):
      models[slug] = record
  return models


def _fetch(url: str) -> str:
  request = urllib.request.Request(url, headers={
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64) " + store.USER_AGENT,
    "accept": "text/html",
  })
  with urllib.request.urlopen(request, timeout=30) as response:
    return response.read().decode("utf-8", "replace")


def fetch_models(force: bool = False) -> dict[str, Any]:
  """{"models": {slug: record}, "fetchedAt": epoch, "warning": str | None}."""
  cached = store.read_data("aa-web")
  fresh = (isinstance(cached, dict) and isinstance(cached.get("models"), dict)
           and 0 <= time.time() - float(cached.get("at") or 0) < CACHE_TTL_SECONDS)
  if fresh and not force:
    return {"models": cached["models"], "fetchedAt": cached["at"], "warning": None}

  error_text = "no page parsed"
  for url in PAGES:
    try:
      models = parse_models(_fetch(url))
    except (urllib.error.URLError, TimeoutError, OSError) as error:
      error_text = str(error)
      continue
    # A real page has hundreds of records; a handful means the layout changed.
    if len(models) >= 50:
      now = time.time()
      store.write_data("aa-web", {"at": now, "models": models, "source": url})
      return {"models": models, "fetchedAt": now, "warning": None}
    error_text = f"only {len(models)} models found on {url}"

  if isinstance(cached, dict) and isinstance(cached.get("models"), dict):
    return {"models": cached["models"], "fetchedAt": cached.get("at"),
            "warning": f"Couldn't refresh Artificial Analysis ({error_text}); showing the last copy."}
  return {"models": {}, "fetchedAt": None,
          "warning": f"Couldn't read Artificial Analysis ({error_text})."}
