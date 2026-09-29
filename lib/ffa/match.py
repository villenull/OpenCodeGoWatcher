"""Fuzzy join from an opencode model id to an Artificial Analysis entry.

Ported from server/match.ts. This is the fiddliest logic in the port and the
part most worth testing: a wrong match publishes a fabricated number as if it
were a real benchmark result.
"""

from __future__ import annotations

import re
from typing import Any

_VERSION_TOKEN = re.compile(r"\d+(?:\.\d+)*")
_NON_ALNUM = re.compile(r"[^a-z0-9.]+")


def normalise(value: str) -> str:
  """Punctuation the two catalogues spell differently: dots vs dashes, v-prefixes."""
  text = _NON_ALNUM.sub("-", value.lower())
  text = text.replace(".", "-")
  text = re.sub(r"^v(?=\d)", "", text)
  text = re.sub(r"-+", "-", text)
  return text.strip("-")


def without_free_marker(model_id: str) -> str:
  """Strip the free marker so `space-bunny-free` can meet `space-bunny`."""
  return normalise(re.sub(r"-free$", "", model_id))


def version_tokens(value: str) -> list[str]:
  return _VERSION_TOKEN.findall(value)


def versions_agree(left: str, right: str) -> bool:
  """Two catalogues will never agree on spelling, but they do agree on which
  version of a thing this is. Any candidate whose version numbers differ is
  rejected outright, which is what stops `longcat-2.5-preview` from quietly
  inheriting LongCat 2.0's numbers."""
  left_versions = version_tokens(left)
  right_versions = version_tokens(right)
  if not left_versions or not right_versions:
    return True
  return left_versions == right_versions


def token_set(value: str) -> set[str]:
  return {token for token in normalise(value).split("-") if token}


def overlap(left: str, right: str) -> float:
  left_tokens = token_set(left)
  right_tokens = token_set(right)
  if not left_tokens or not right_tokens:
    return 0.0
  shared = len(left_tokens & right_tokens)
  return shared / min(len(left_tokens), len(right_tokens))


def match_aa_model(opencode_id: str, catalogue: list[dict[str, Any]]) -> dict[str, Any] | None:
  """Best AA entry for an opencode model id, or None when the match is not
  confident enough to publish as a number.

  Stealth models are expected to land on None, which is the whole point: a
  free model nobody has published numbers for should show as unmeasured rather
  than inherit a neighbour's score.
  """
  target = without_free_marker(opencode_id)

  for model in catalogue:
    if normalise(model["slug"]) == target:
      return {"model": model, "method": "exact"}

  for model in catalogue:
    slug = normalise(model["slug"])
    if not versions_agree(target, slug):
      continue
    if target in slug or slug in target:
      return {"model": model, "method": "contains"}

  best: dict[str, Any] | None = None
  best_score = 0.0
  for model in catalogue:
    slug = normalise(model["slug"])
    if not versions_agree(target, slug):
      continue
    score = overlap(target, slug)
    if best is None or score > best_score:
      best, best_score = model, score

  # Require the shortest name to be almost entirely contained, so "hy3" cannot
  # latch onto "minicpm5-2b".
  if best is not None and best_score >= 0.99:
    return {"model": best, "method": "tokens"}
  return None
