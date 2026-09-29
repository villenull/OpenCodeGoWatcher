"""Artificial Analysis leaderboard client.

Ported from server/aa.ts. Every field is treated as optional on purpose: the
window has to render when a model has no speed measurement or no index, and a
strict schema would throw away the other 600 models over one missing field.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from . import store

AA_BASE = "https://artificialanalysis.ai/api/v2"
MAX_PAGES = 12


class AaAuthError(RuntimeError):
  def __init__(self) -> None:
    super().__init__("Artificial Analysis rejected the API key (401).")


def _number(value: Any) -> float | None:
  return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _normalise_model(raw: Any) -> dict[str, Any] | None:
  if not isinstance(raw, dict):
    return None
  name, slug = raw.get("name"), raw.get("slug")
  if not isinstance(name, str) or not isinstance(slug, str) or not name or not slug:
    return None

  creator = raw.get("model_creator")
  creator_name = creator.get("name") if isinstance(creator, dict) else None

  evaluations = raw.get("evaluations")
  intelligence = None
  if isinstance(evaluations, dict):
    intelligence = _number(evaluations.get("artificial_analysis_intelligence_index"))

  performance = raw.get("performance")
  tokens_per_second = None
  if isinstance(performance, dict):
    tokens_per_second = _number(performance.get("median_output_tokens_per_second"))

  release_date = raw.get("release_date")
  return {
    "name": name,
    "slug": slug,
    "creator": creator_name if isinstance(creator_name, str) and creator_name else "Unknown",
    "releaseDate": release_date if isinstance(release_date, str) and release_date else None,
    "intelligence": intelligence,
    "tokensPerSecond": tokens_per_second,
  }


def _normalise_version(value: Any) -> str | None:
  if value is None:
    return None
  return f"v{value}"


def fetch_aa_catalogue() -> dict[str, Any]:
  """Paginate the free-tier endpoint. The non-/free sibling is Pro+ and 403s on
  a free key, so the free shape is the only thing a free key can read."""
  key = store.aa_api_key()
  if not key:
    return {"models": [], "indexVersion": None, "warnings": ["No Artificial Analysis API key configured yet."]}

  models: list[dict[str, Any]] = []
  warnings: list[str] = []
  index_version: str | None = None

  for page in range(1, MAX_PAGES + 1):
    url = f"{AA_BASE}/language/models/free"
    if page > 1:
      url += "?" + urllib.parse.urlencode({"page": page})

    request = urllib.request.Request(url, headers={
      "x-api-key": key,
      "accept": "application/json",
      "user-agent": store.USER_AGENT,
    })

    try:
      with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
    except urllib.error.HTTPError as error:
      if error.code == 401:
        raise AaAuthError() from error
      if error.code == 429:
        warnings.append("Artificial Analysis rate limit hit (100 requests/24h on the free tier). Showing cached data.")
        break
      warnings.append(f"Artificial Analysis returned {error.code}; leaderboard unavailable.")
      break
    except Exception as error:  # noqa: BLE001 - a warning, never fatal
      warnings.append(f"Artificial Analysis unreachable: {error}")
      break

    if not isinstance(body, dict):
      warnings.append("Artificial Analysis returned an unrecognised payload.")
      break

    if index_version is None:
      index_version = _normalise_version(body.get("intelligence_index_version"))

    rows = body.get("data")
    if isinstance(rows, list):
      for row in rows:
        model = _normalise_model(row)
        if model is not None:
          models.append(model)

    pagination = body.get("pagination")
    if not isinstance(pagination, dict) or not pagination.get("has_more"):
      break

  return {"models": models, "indexVersion": index_version, "warnings": warnings}
