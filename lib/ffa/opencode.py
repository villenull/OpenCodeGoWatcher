"""The OpenCode Go catalogue, and what counts as free.

Ported from server/opencode.ts.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Any

from . import store

GO_MODELS_URL = "https://opencode.ai/zen/go/v1/models"

# opencode's Go catalogue exposes ids only — no price field — so "free" has to be
# inferred. The `-free` suffix is the reliable signal; EXTRA_FREE is a
# deliberate escape hatch in case Go ships a stealth freebie without one.
SUFFIX_FREE = re.compile(r"-free$")
EXTRA_FREE = {"big-pickle"}

# Worth knowing before anyone points a real repo at one of these. Sourced from
# the Privacy section of the opencode docs, which distinguishes the two
# zero-retention providers from the rest.
NOTES = {
  "space-bunny-free": "stealth model · zero-retention, no training",
  "longcat-2.5-preview-free": "zero-retention, no training",
  "big-pickle": "stealth model · prompts may be used to improve it",
}

TRAINING_RISK = "limited-time free · prompts may be used to improve it"


def prettify(model_id: str) -> str:
  def cap(part: str) -> str:
    # A part starting with a digit is a version or a size, and capitalising it
    # would read wrong: "Longcat 2.5 Preview Free", not "Longcat 2.5".
    return part if part[:1].isdigit() else part[:1].upper() + part[1:]

  return " ".join(cap(part) for part in model_id.split("-"))


def is_free_id(model_id: str) -> bool:
  return bool(SUFFIX_FREE.search(model_id)) or model_id in EXTRA_FREE


def fetch_go_models() -> list[dict[str, Any]]:
  request = urllib.request.Request(GO_MODELS_URL, headers={
    "accept": "application/json",
    "user-agent": store.USER_AGENT,
  })
  try:
    with urllib.request.urlopen(request, timeout=20) as response:
      body = json.load(response)
  except urllib.error.HTTPError as error:
    raise RuntimeError(f"opencode go catalogue returned {error.code}") from error
  except Exception as error:  # noqa: BLE001 - surfaced as a warning by the caller
    raise RuntimeError(f"could not reach the opencode go catalogue: {error}") from error

  rows = body.get("data") if isinstance(body, dict) else None
  if not isinstance(rows, list):
    rows = []

  models = []
  for row in rows:
    model_id = row.get("id") if isinstance(row, dict) else None
    if not isinstance(model_id, str) or not model_id:
      continue
    models.append({
      "id": model_id,
      "label": prettify(model_id),
      "suffixed": bool(SUFFIX_FREE.search(model_id)),
      "note": NOTES.get(model_id, TRAINING_RISK),
    })
  return models


def filter_free(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
  return [model for model in models if is_free_id(model["id"])]
