"""Snapshot assembly: the view model the two charts render.

Ported from server/dashboard.ts. The structure is the important part — each of
`rows.intelligence` and `rows.speed` is a *list* of blocks, not one block,
because AA's Intelligence Index runs 0-70 while our own Omniscience run runs
-100..100. Putting both on one axis would produce a chart that looks
authoritative and is not, so they stay separate blocks inside one card.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

from . import aa, eval as eval_mod, match, opencode, store

# The Go catalogue and the AA leaderboard are cheap, so the window re-pulls them
# on this cadence. It is also what keeps the free AA tier's 100 requests/24h
# budget intact: one full build costs up to 12 paginated requests.
CACHE_TTL_SECONDS = 6 * 60 * 60

# How many non-free AA models to show for scale next to the free ones.
CONTEXT_LIMIT = 10


def _now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def short_label(name: str) -> str:
  """A model name with AA's configuration parenthetical removed.

  Artificial Analysis names entries like
  "Claude Opus 5.5 (Adaptive Reasoning, Max Effort, Default Fallback)". Under a
  vertical column that is mostly parenthetical, and the parenthetical is config
  metadata rather than a different model family — so it is dropped *for display
  only*. The full name stays on the row as `label`, because the effort variants
  genuinely are separate AA entries and merging them in the data would be wrong.
  """
  index = name.find(" (")
  return name[:index] if index > 0 else name


def _add_short_labels(blocks: list[dict[str, Any]]) -> None:
  for block in blocks:
    for row in block.get("rows") or []:
      row["shortLabel"] = short_label(str(row.get("label") or ""))
      row["configLabel"] = config_label(str(row.get("label") or ""))


def build_domain(values: list[float]) -> dict[str, float]:
  """Always clamps min <= 0 <= max, so a bar can extend left of zero on the
  diverging Omniscience scale. `zero` is that line as a 0..1 fraction of the
  plot width."""
  maximum = max([*values, 0.0])
  minimum = min([*values, 0.0])
  span = (maximum - minimum) or 1.0
  return {"min": minimum, "max": maximum, "zero": (0.0 - minimum) / span}


# Token abbreviations for the configuration line under a column. Artificial
# Analysis publishes one entry per effort level, so the parenthetical is mostly
# these words, and "Adaptive Reasoning, Max Effort, Default Fallback" is too long
# to sit under a narrow column.
_CONFIG_TOKENS = (
  ("adaptive reasoning", "adaptive"),
  ("default fallback", "fallback"),
  ("no fallback", "no fallback"),
)


def config_label(name: str) -> str:
  """The unusual settings an AA number was measured at, for the line under a column.

  Maximum effort is dropped rather than shown: `_context_rows` prefers an entry
  AA labels (max), so "max" is what a reader already assumes, and printing it
  ten times is what pushes these labels into their neighbours. What is worth the
  room is the deviation from that default.

  "GPT-6 Astra (max)" -> "" (nothing to add);
  "Claude Opus 5.5 (Adaptive Reasoning, Max Effort, Default Fallback)" ->
  "adaptive·fallback";
  "Gemini 3.7 Flash (high)" -> "high".
  """
  start = name.find(" (")
  end = name.rfind(")")
  if start < 0 or end <= start:
    return ""
  inner = name[start + 2:end]
  tokens = []
  for raw in inner.split(","):
    # Lowercased throughout so every config line reads the same way, whatever
    # casing AA used. A size like "3.3B" becomes "3.3b", which is consistent
    # with "max" and "adaptive" beside it and costs nothing here.
    token = raw.strip().lower()
    for long, short in _CONFIG_TOKENS:
      token = token.replace(long, short)
    token = re.sub(r"\s+effort\b", "", token)
    # Strip maximum effort wherever it appears, not just as a whole token, so
    # "3.3B max" reduces to "3.3b".
    token = re.sub(r"\bmax\b", "", token).strip(" ,")
    # Any fallback collapses to "fallback", except an explicit "no fallback",
    # which is the distinction worth keeping. "Opus 4.8 Fallback" names which
    # model stood in, which is a detail this line has no room for.
    if "no fallback" in token:
      token = "no fallback"
    elif "fallback" in token:
      token = "fallback"
    if token:
      tokens.append(token)
  # No spaces around the separator: a column is about 110px wide, and the wider
  # tokens are 16 characters.
  return "·".join(tokens)


def _is_max_effort(name: str) -> bool:
  """True for an entry AA labels as running at maximum effort."""
  return "(max)" in name.lower()


def _context_rows(
  catalogue: list[dict[str, Any]],
  used_slugs: set[str],
  field: str,
  scale: str,
) -> list[dict[str, Any]]:
  """Top paid models for scale — one row per base model.

  AA's API applies no filter: 684 entries covering 472 base names, 133 of which
  have several variants, because AA publishes a score per effort level and
  reasoning configuration. Taking the ten highest entries raw therefore fills
  half the chart with one model — five rows of Claude Opus 5.5 at three effort
  settings — which says nothing about where a model sits relative to the rest.

  So one row per base name, preferring the entry AA labels (max) and falling back
  to the highest when there isn't one. Preferring (max) rather than simply
  taking the best score keeps the numbers comparable: every column is then a
  full-effort number, rather than each model being shown at whichever
  configuration happens to have flattered it most.
  """
  best: dict[str, tuple[dict[str, Any], float]] = {}
  for model in catalogue:
    if model["slug"] in used_slugs:
      continue
    value = model.get(field)
    if value is None:
      continue
    base = short_label(model["name"])
    current = best.get(base)
    if current is None:
      best[base] = (model, float(value))
      continue
    challenger_max, current_max = _is_max_effort(model["name"]), _is_max_effort(current[0]["name"])
    # A (max) entry always beats a non-max one; otherwise the higher score wins.
    if (challenger_max, float(value)) > (current_max, current[1]):
      best[base] = (model, float(value))

  ordered = sorted(best.values(), key=lambda pair: -pair[1])[:CONTEXT_LIMIT]
  return [{
    "key": f"aa:{model['slug']}",
    "label": model["name"],
    "value": value,
    "source": "aa",
    "scale": scale,
    "isFree": False,
    "aaSlug": model["slug"],
  } for model, value in ordered]


def _latest_grades(history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
  latest: dict[str, dict[str, Any]] = {}
  for grade in history:
    model_id = grade.get("opencodeId")
    if isinstance(model_id, str) and model_id not in latest:
      latest[model_id] = grade
  return latest


def build_snapshot(force: bool = False) -> dict[str, Any]:
  if not force:
    cached = store.read_data("snapshot")
    if isinstance(cached, dict) and isinstance(cached.get("snapshot"), dict):
      age = time.time() - float(cached.get("at") or 0)
      if 0 <= age < CACHE_TTL_SECONDS:
        return cached["snapshot"]

  warnings: list[str] = []
  free = opencode.filter_free(opencode.fetch_go_models())

  catalogue: list[dict[str, Any]] = []
  index_version: str | None = None
  try:
    result = aa.fetch_aa_catalogue()
    catalogue = result["models"]
    index_version = result["indexVersion"]
    warnings.extend(result["warnings"])
  except aa.AaAuthError:
    warnings.append("Artificial Analysis rejected the API key. Check it in Settings.")
  except Exception as error:  # noqa: BLE001 - a warning, never fatal
    warnings.append(str(error))

  speed_cache = store.read_data("speed")
  speed_rows: dict[str, dict[str, Any]] = {}
  if isinstance(speed_cache, dict) and isinstance(speed_cache.get("rows"), list):
    speed_rows = {row["opencodeId"]: row for row in speed_cache["rows"]
                  if isinstance(row, dict) and isinstance(row.get("opencodeId"), str)}
  grades = _latest_grades(store.read_eval_history())

  matches = {model["id"]: match.match_aa_model(model["id"], catalogue) for model in free}
  used_slugs = {entry["model"]["slug"] for entry in matches.values() if entry}

  # --- Chart 1: intelligence --------------------------------------------------
  intelligence_rows: list[dict[str, Any]] = []
  for model in free:
    entry = matches.get(model["id"])
    if entry and entry["model"].get("intelligence") is not None:
      intelligence_rows.append({
        "key": f"free:{model['id']}",
        "label": model["label"],
        "value": entry["model"]["intelligence"],
        "source": "aa",
        "scale": "aa-index",
        "isFree": True,
        "opencodeId": model["id"],
        "aaSlug": entry["model"]["slug"],
        "note": model.get("note"),
      })
  intelligence_rows.extend(_context_rows(catalogue, used_slugs, "intelligence", "aa-index"))
  intelligence_rows.sort(key=lambda row: -(row.get("value") or 0))

  omniscience_rows: list[dict[str, Any]] = []
  for model in free:
    grade = grades.get(model["id"])
    if not grade:
      continue
    # The Omniscience index is -1..1; expressed as points so it reads like the
    # index AA publishes rather than a bare fraction.
    omniscience_rows.append({
      "key": f"omni:{model['id']}",
      "label": model["label"],
      "value": round(float(grade.get("index", 0)) * 100, 1),
      "source": "self",
      "scale": "omniscience",
      "isFree": True,
      "opencodeId": model["id"],
      "note": (f"accuracy {round(float(grade.get('accuracy', 0)) * 100)}%"
               f" · hallucination {round(float(grade.get('hallucinationRate', 0)) * 100)}%"
               f" · {grade.get('total')} questions"),
    })
  omniscience_rows.sort(key=lambda row: -(row.get("value") or 0))

  # --- Chart 2: speed ---------------------------------------------------------
  speed_aa_rows: list[dict[str, Any]] = []
  speed_self_rows: list[dict[str, Any]] = []
  for model in free:
    entry = matches.get(model["id"])
    if entry and entry["model"].get("tokensPerSecond") is not None:
      speed_aa_rows.append({
        "key": f"free:{model['id']}",
        "label": model["label"],
        "value": round(entry["model"]["tokensPerSecond"]),
        "source": "aa",
        "scale": "aa-speed",
        "isFree": True,
        "opencodeId": model["id"],
        "aaSlug": entry["model"]["slug"],
        "note": model.get("note"),
      })
      continue
    probed = speed_rows.get(model["id"])
    if probed and probed.get("tokensPerSecond") is not None:
      speed_self_rows.append({
        "key": f"self:{model['id']}",
        "label": model["label"],
        "value": probed["tokensPerSecond"],
        "source": "self",
        "scale": "aa-speed",
        "isFree": True,
        "opencodeId": model["id"],
        "note": f"self-measured · ~{probed.get('tokens') or '?'} output tokens",
      })
  speed_combined = sorted(
    [*speed_aa_rows, *speed_self_rows, *_context_rows(catalogue, used_slugs, "tokensPerSecond", "aa-speed")],
    key=lambda row: -(row.get("value") or 0),
  )

  unmatched = [
    model["id"] for model in free
    if not matches.get(model["id"])
    and not (speed_rows.get(model["id"]) or {}).get("tokensPerSecond")
    and not grades.get(model["id"])
  ]

  if not free:
    warnings.append("opencode Go is serving no free models right now.")

  intelligence_blocks = [{
    "scale": "aa-index",
    "caption": "Artificial Analysis Intelligence Index",
    "unit": "index · higher is better",
    "domain": build_domain([row.get("value") or 0 for row in intelligence_rows]),
    "rows": intelligence_rows,
  }]
  if omniscience_rows:
    intelligence_blocks.append({
      "scale": "omniscience",
      "caption": "Our run · AA-Omniscience (public 600q)",
      "unit": "index −100…100 · higher is better",
      "domain": build_domain([row.get("value") or 0 for row in omniscience_rows]),
      "rows": omniscience_rows,
    })

  snapshot = {
    "fetchedAt": _now_iso(),
    "freeModels": free,
    "rows": {
      "intelligence": intelligence_blocks,
      "speed": [{
        "scale": "aa-speed",
        "caption": "Output speed",
        "unit": "output tokens/second · higher is better",
        "domain": build_domain([row.get("value") or 0 for row in speed_combined]),
        "rows": speed_combined,
      }],
    },
    "unmatched": unmatched,
    "warnings": warnings,
    "speedProbedAt": speed_cache.get("probedAt") if isinstance(speed_cache, dict) else None,
    "eval": eval_mod.read_state(),
    "aa": {
      "configured": bool(store.aa_api_key()),
      "modelCount": len(catalogue),
      "indexVersion": index_version,
    },
  }

  _add_short_labels(snapshot["rows"]["intelligence"])
  _add_short_labels(snapshot["rows"]["speed"])

  store.write_data("snapshot", {"at": time.time(), "snapshot": snapshot})
  return snapshot
