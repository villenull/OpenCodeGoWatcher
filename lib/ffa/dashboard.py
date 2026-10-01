"""Snapshot assembly: the view model the two charts render.

Two charts, side by side: SciCode (the share of SciCode's sub-problems a model's
code passes) and output speed. Both are numbers Artificial Analysis publishes
for the paid models and that this plugin measures the same way for the free
ones, so each pair genuinely shares an axis. `rows.intelligence` and
`rows.speed` stay lists of blocks so a chart can be added without reshaping
the window.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

from . import aaweb, eval as eval_mod, match, opencode, scicode, store

# How long a built snapshot is reused. The AA website data is cached for a day
# on its own (aaweb); this mostly spares the Go catalogue request.
CACHE_TTL_SECONDS = 6 * 60 * 60

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
      # A free model's effort isn't in its name; its row carries it already.
      row.setdefault("configLabel", config_label(str(row.get("label") or "")))


def build_domain(values: list[float]) -> dict[str, float]:
  """Always clamps min <= 0 <= max, so a bar could extend left of zero on a
  diverging scale. `zero` is that line as a 0..1 fraction of the plot width."""
  maximum = max([*values, 0.0])
  minimum = min([*values, 0.0])
  span = (maximum - minimum) or 1.0
  return {"min": minimum, "max": maximum, "zero": (0.0 - minimum) / span}


_EFFORT = re.compile(r"\b(minimal|low|medium|high|xhigh)\b")


def config_label(name: str) -> str:
  """The effort level an AA number was measured at, or "" for maximum effort.

  AA publishes one entry per effort level and names it in a parenthetical,
  e.g. "Claude Opus 5.5 (Adaptive Reasoning, Medium Effort, Default Fallback)"
  -> "medium". Maximum is what `_top_context` picks and what a reader
  assumes, so it adds nothing; reasoning mode and fallback are detail the
  chart has no room for.
  """
  start = name.find(" (")
  end = name.rfind(")")
  if start < 0 or end <= start:
    return ""
  found = _EFFORT.search(name[start + 2:end].lower())
  return found.group(1) if found else ""


def _is_max_effort(name: str) -> bool:
  """True for an entry AA runs at maximum effort — "(max)", "Max Effort", or
  no effort named at all — i.e. whenever there is no lower effort to show."""
  return config_label(name) == ""


def _latest_results(history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
  latest: dict[str, dict[str, Any]] = {}
  for result in history:
    model_id = result.get("opencodeId")
    if isinstance(model_id, str) and model_id not in latest:
      latest[model_id] = result
  return latest


# The models you orchestrate with, at the effort you run them at. Artificial
# Analysis publishes one entry per effort level; these are the medium ones.
# Override with "orchestrators": ["slug", ...] in settings.json.
DEFAULT_ORCHESTRATORS = (
  "claude-opus-5-5-medium",
  "claude-sonnet-5-5-medium",
  "gpt-6-1-sol-medium",
  "gpt-6-astra-medium",
)

# How many of AA's top models to show for scale, besides the orchestrators.
TOP_CONTEXT = 4


def orchestrator_slugs() -> list[str]:
  settings = store.read_json(store.settings_path())
  chosen = settings.get("orchestrators") if isinstance(settings, dict) else None
  if isinstance(chosen, list) and all(isinstance(slug, str) for slug in chosen) and chosen:
    return chosen
  return list(DEFAULT_ORCHESTRATORS)


def _top_context(models: list[dict[str, Any]], exclude_releases: set[str]) -> list[dict[str, Any]]:
  """AA's strongest current models, one entry per release, preferring the (max)
  entry, skipping retired ones and releases already on the chart as an
  orchestrator."""
  best: dict[str, dict[str, Any]] = {}
  for model in models:
    if (model.get("intelligence") is None or model.get("deprecated")
        or model["releaseSlug"] in exclude_releases):
      continue
    current = best.get(model["releaseSlug"])
    rank = (_is_max_effort(model["name"]), model["intelligence"])
    if current is None or rank > (_is_max_effort(current["name"]), current["intelligence"]):
      best[model["releaseSlug"]] = model
  return sorted(best.values(), key=lambda model: -model["intelligence"])[:TOP_CONTEXT]


def _aa_row(model: dict[str, Any], field: str, scale: str, role: str, factor: float = 1.0) -> dict[str, Any] | None:
  value = model.get(field)
  if value is None:
    return None
  return {
    "key": f"aa:{model['slug']}",
    "label": model["name"],
    "value": round(float(value) * factor, 1),
    "source": "aa",
    "scale": scale,
    "isFree": False,
    "role": role,
    "aaSlug": model["slug"],
  }


def _block(scale: str, caption: str, unit: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
  rows = sorted(rows, key=lambda row: -(row.get("value") or 0))
  return {
    "scale": scale,
    "caption": caption,
    "unit": unit,
    "domain": build_domain([row.get("value") or 0 for row in rows]),
    "rows": rows,
  }


def build_snapshot(force: bool = False) -> dict[str, Any]:
  if not force:
    cached = store.read_data("snapshot")
    if isinstance(cached, dict) and isinstance(cached.get("snapshot"), dict):
      age = time.time() - float(cached.get("at") or 0)
      if 0 <= age < CACHE_TTL_SECONDS:
        return cached["snapshot"]

  warnings: list[str] = []
  free = opencode.filter_free(opencode.fetch_go_models())

  aa_result = aaweb.fetch_models(force=force)
  if aa_result["warning"]:
    warnings.append(aa_result["warning"])
  by_slug: dict[str, dict[str, Any]] = aa_result["models"]
  catalogue = list(by_slug.values())

  orchestrators = [by_slug[slug] for slug in orchestrator_slugs() if slug in by_slug]
  missing = [slug for slug in orchestrator_slugs() if slug not in by_slug]
  if missing and by_slug:
    warnings.append("Artificial Analysis has no entry for: " + ", ".join(missing))
  context = _top_context(catalogue, {model["releaseSlug"] for model in orchestrators})
  paid = [(model, "orchestrator") for model in orchestrators] + [(model, "context") for model in context]

  speed_cache = store.read_data("speed")
  speed_rows: dict[str, dict[str, Any]] = {}
  if isinstance(speed_cache, dict) and isinstance(speed_cache.get("rows"), list):
    speed_rows = {row["opencodeId"]: row for row in speed_cache["rows"]
                  if isinstance(row, dict) and isinstance(row.get("opencodeId"), str)}
  results = _latest_results(store.read_scicode_history())
  matches = {model["id"]: match.match_aa_model(model["id"], catalogue) for model in free}

  def free_row(model: dict[str, Any], key: str, value: float, source: str, scale: str, note: str | None) -> dict[str, Any]:
    return {"key": key, "label": model["label"], "value": value, "source": source, "scale": scale,
            "isFree": True, "role": "free", "opencodeId": model["id"], "note": note}

  # --- SciCode: AA's published share for the paid models, our run for the free
  # ones, as a percentage of sub-problems passed.
  scicode_rows = [row for model, role in paid if (row := _aa_row(model, "scicode", "scicode", role, 100.0))]
  for model in free:
    result = results.get(model["id"])
    if not result:
      continue
    row = free_row(model, f"scicode:{model['id']}", round(float(result.get("score", 0)) * 100, 1),
                   "self", "scicode",
                   f"our run · {result.get('passed')}/{result.get('attempted')} sub-problems"
                   + (f" · {result['skipped']} unanswered, left out" if result.get("skipped") else ""))
    row["configLabel"] = result.get("effort") or ""
    scicode_rows.append(row)

  # --- Speed --------------------------------------------------------------------
  speed_block_rows = [row for model, role in paid if (row := _aa_row(model, "tokensPerSecond", "aa-speed", role))]
  free_speed: dict[str, float] = {}
  for model in free:
    entry = matches.get(model["id"])
    if entry and entry["model"].get("tokensPerSecond") is not None:
      value = round(entry["model"]["tokensPerSecond"])
      speed_block_rows.append(free_row(model, f"free:{model['id']}", value, "aa", "aa-speed", model.get("note")))
    elif (probed := speed_rows.get(model["id"])) and probed.get("tokensPerSecond") is not None:
      value = probed["tokensPerSecond"]
      speed_block_rows.append(free_row(model, f"self:{model['id']}", value, "self", "aa-speed",
                                       f"self-measured · ~{probed.get('tokens') or '?'} output tokens"))
    else:
      continue
    free_speed[model["id"]] = float(value)

  if not free:
    warnings.append("opencode Go is serving no free models right now.")

  intelligence_blocks = [
    _block("scicode", "SciCode", "% of sub-problems solved · higher is better", scicode_rows),
  ]
  snapshot = {
    "fetchedAt": _now_iso(),
    "freeModels": free,
    "rows": {
      "intelligence": intelligence_blocks,
      "speed": [_block("aa-speed", "Output speed", "tokens/second · higher is better", speed_block_rows)],
    },
    "unmatched": [model["id"] for model in free if model["id"] not in results and model["id"] not in free_speed],
    "warnings": warnings,
    "speedProbedAt": speed_cache.get("probedAt") if isinstance(speed_cache, dict) else None,
    "eval": eval_mod.read_state(),
    "scicode": {"downloaded": scicode.data_ready()},
    # Free models with no result yet from an operation only we can run; the
    # window rings the matching button red while these are non-empty.
    "pending": {
      "intelligence": [model["id"] for model in free if model["id"] not in results],
      "speed": [model["id"] for model in free if model["id"] not in speed_rows],
    },
    "aa": {
      "source": "artificialanalysis.ai",
      "modelCount": len(catalogue),
      "fetchedAt": aa_result["fetchedAt"],
    },
  }

  _add_short_labels(snapshot["rows"]["intelligence"])
  _add_short_labels(snapshot["rows"]["speed"])

  store.write_data("snapshot", {"at": time.time(), "snapshot": snapshot})
  return snapshot
