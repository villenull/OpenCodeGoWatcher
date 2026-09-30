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

from . import aaweb, eval as eval_mod, match, opencode, store

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
      row["configLabel"] = config_label(str(row.get("label") or ""))


def build_domain(values: list[float]) -> dict[str, float]:
  """Always clamps min <= 0 <= max, so a bar can extend left of zero on the
  diverging Omniscience scale. `zero` is that line as a 0..1 fraction of the
  plot width."""
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


def _latest_grades(history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
  latest: dict[str, dict[str, Any]] = {}
  for grade in history:
    model_id = grade.get("opencodeId")
    if isinstance(model_id, str) and model_id not in latest:
      latest[model_id] = grade
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


def _aa_row(model: dict[str, Any], field: str, scale: str, role: str) -> dict[str, Any] | None:
  value = model.get(field)
  if value is None:
    return None
  return {
    "key": f"aa:{model['slug']}",
    "label": model["name"],
    "value": round(float(value), 1),
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


def _summary(free: list[dict[str, Any]], omni: dict[str, float], speed: dict[str, float],
             orch_omni: list[float], orch_speed: list[float]) -> list[str]:
  """One plain line per free model, measured against the orchestrators, plus
  which free model came out ahead. Directional: our Omniscience run is a
  100-question sample graded by Big Pickle, AA's is 6,000 with their grader."""
  lines = []
  median_speed = sorted(orch_speed)[len(orch_speed) // 2] if orch_speed else None
  for model in free:
    parts = []
    if model["id"] in omni and orch_omni:
      parts.append(f"Omniscience {omni[model['id']]:.0f} vs your orchestrators' "
                   f"{min(orch_omni):.0f}–{max(orch_omni):.0f}")
    if model["id"] in speed and median_speed:
      parts.append(f"{speed[model['id']] / median_speed:.1f}× their typical speed")
    if parts:
      lines.append(f"{model['label']}: " + " · ".join(parts))
  scored = [model for model in free if model["id"] in omni]
  if len(scored) > 1:
    best = max(scored, key=lambda model: omni[model["id"]])
    lines.append(f"Smarter free model right now: {best['label']}")
  return lines


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
  grades = _latest_grades(store.read_eval_history())
  matches = {model["id"]: match.match_aa_model(model["id"], catalogue) for model in free}

  def free_row(model: dict[str, Any], key: str, value: float, source: str, scale: str, note: str | None) -> dict[str, Any]:
    return {"key": key, "label": model["label"], "value": value, "source": source, "scale": scale,
            "isFree": True, "role": "free", "opencodeId": model["id"], "note": note}

  # --- Smarts: Omniscience, the one test both sides take --------------------
  omni_rows = [row for model, role in paid if (row := _aa_row(model, "omniscience", "omniscience", role))]
  free_omni: dict[str, float] = {}
  for model in free:
    grade = grades.get(model["id"])
    if not grade:
      continue
    # Our index is -1..1; as points it reads on AA's -100..100 scale.
    value = round(float(grade.get("index", 0)) * 100, 1)
    free_omni[model["id"]] = value
    omni_rows.append(free_row(model, f"omni:{model['id']}", value, "self", "omniscience",
                              f"our run · {grade.get('total')} questions · "
                              f"accuracy {round(float(grade.get('accuracy', 0)) * 100)}%"
                              + (f" · {grade['skipped']} unanswered, left out" if grade.get("skipped") else "")))

  # --- Smarts: AA's overall index, for context --------------------------------
  index_rows = [row for model, role in paid if (row := _aa_row(model, "intelligence", "aa-index", role))]
  for model in free:
    entry = matches.get(model["id"])
    if entry and entry["model"].get("intelligence") is not None:
      index_rows.append(free_row(model, f"free:{model['id']}", round(entry["model"]["intelligence"], 1),
                                 "aa", "aa-index", model.get("note")))

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
    _block("omniscience", "AA-Omniscience", "−100…100 · higher is better", omni_rows),
    _block("aa-index", "AA Intelligence Index", "higher is better", index_rows),
  ]
  snapshot = {
    "fetchedAt": _now_iso(),
    "freeModels": free,
    "rows": {
      "intelligence": intelligence_blocks,
      "speed": [_block("aa-speed", "Output speed", "tokens/second · higher is better", speed_block_rows)],
    },
    "summary": _summary(free, free_omni, free_speed,
                        [model["omniscience"] for model in orchestrators if model.get("omniscience") is not None],
                        [model["tokensPerSecond"] for model in orchestrators if model.get("tokensPerSecond") is not None]),
    "unmatched": [model["id"] for model in free if model["id"] not in free_omni and model["id"] not in free_speed],
    "warnings": warnings,
    "speedProbedAt": speed_cache.get("probedAt") if isinstance(speed_cache, dict) else None,
    "eval": eval_mod.read_state(),
    # Free models with no result yet from an operation only we can run; the
    # window rings the matching button red while these are non-empty.
    "pending": {
      "intelligence": [model["id"] for model in free if model["id"] not in grades],
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
