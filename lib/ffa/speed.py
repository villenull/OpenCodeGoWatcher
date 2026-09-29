"""Self-measured output tokens per second.

Ported from server/speed.ts. The window deliberately excludes time-to-first-token
because that is how Artificial Analysis measures it, and it is the only reason
our number and theirs belong on one axis.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from . import store

GO_CHAT_URL = "https://opencode.ai/zen/go/v1/chat/completions"
SAMPLES = 2

# A window shorter than this is not a measurement. The gateway does not stream
# at a steady cadence: sometimes the whole completion arrives buffered in a
# single read, and then "time between first and last byte" is the time to
# receive a finished response, not the time to generate it. Publishing that as
# tokens/second produced figures in the hundreds of thousands, which is faster
# than light and obviously wrong. Such a sample is dropped instead.
MIN_WINDOW_SECONDS = 0.25

MAX_TOKENS = 700

# The probe prompt differs per sample on purpose. An identical prompt would let
# the gateway's prompt cache serve sample 2 instantly, and a cached sample's
# "speed" is an artefact of the cache rather than of the model — median-ing one
# real sample with one cached sample lands somewhere between the truth and
# nonsense.
COUNT_PROMPTS = [
  "Count from 1 to 250, one number per line, nothing else. Do not stop early.",
  "Count from 251 to 500, one number per line, nothing else. Do not stop early.",
  "Count from 501 to 750, one number per line, nothing else. Do not stop early.",
]


def _median(values: list[float]) -> float:
  ordered = sorted(values)
  mid = len(ordered) // 2
  if len(ordered) % 2 == 0:
    return (ordered[mid - 1] + ordered[mid]) / 2
  return ordered[mid]


def sample_once(api_key: str, model: str, sample_index: int) -> dict[str, float | int | bool]:
  """One timed generation.

  Timing is per SSE event rather than per socket read, because read boundaries
  reflect network buffering and have nothing to do with when the model emitted
  anything. The window starts at the first event and ends at the last, which
  excludes time-to-first-token — the same thing Artificial Analysis measures, and
  the only reason the two numbers can share an axis.
  """
  prompt = COUNT_PROMPTS[sample_index % len(COUNT_PROMPTS)]
  request = urllib.request.Request(
    GO_CHAT_URL,
    data=json.dumps({
      "model": model,
      "stream": True,
      "stream_options": {"include_usage": True},
      "max_tokens": MAX_TOKENS,
      "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8"),
    headers={
      "authorization": f"Bearer {api_key}",
      "content-type": "application/json",
      "user-agent": store.USER_AGENT,
      "x-opencode-session": store.SESSION_ID,
    },
    method="POST",
  )

  first_event_at: float | None = None
  last_event_at: float | None = None
  reported_tokens: int | None = None
  deltas = 0

  with urllib.request.urlopen(request, timeout=180) as response:
    buffer = ""
    while True:
      chunk = response.read(4096)
      if not chunk:
        break
      buffer += chunk.decode("utf-8", "replace")
      lines = buffer.split("\n")
      buffer = lines.pop()

      for line in lines:
        trimmed = line.strip()
        if not trimmed.startswith("data:"):
          continue
        data = trimmed[5:].strip()
        if data == "[DONE]":
          continue
        try:
          parsed = json.loads(data)
        except json.JSONDecodeError:
          # A partial or non-JSON keepalive frame is not worth failing over.
          continue

        now = time.perf_counter()
        choices = parsed.get("choices") if isinstance(parsed, dict) else None
        content = None
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
          delta = choices[0].get("delta")
          if isinstance(delta, dict):
            content = delta.get("content")
        if isinstance(content, str) and content:
          deltas += 1
          if first_event_at is None:
            first_event_at = now
          last_event_at = now

        usage = parsed.get("usage") if isinstance(parsed, dict) else None
        usage_tokens = usage.get("completion_tokens") if isinstance(usage, dict) else None
        if isinstance(usage_tokens, (int, float)) and usage_tokens > 0:
          reported_tokens = int(usage_tokens)

  # OpenAI-compatible servers do not always honour include_usage. This gateway
  # streams in chunks rather than token by token, so counting deltas can
  # undercount by two orders of magnitude; the fallback is a last resort.
  tokens = reported_tokens if reported_tokens is not None else deltas
  window = (last_event_at - first_event_at) if first_event_at is not None and last_event_at is not None else 0.0
  usable = tokens > 0 and window >= MIN_WINDOW_SECONDS
  return {
    "tokens": tokens,
    "deltas": deltas,
    "windowSeconds": window,
    "tps": (tokens / window) if usable else 0.0,
    "usable": usable,
  }


def probe_model(api_key: str, model_id: str) -> dict[str, Any]:
  try:
    samples = [sample_once(api_key, model_id, index) for index in range(SAMPLES)]
    usable = [sample for sample in samples if sample["usable"]]
    if not usable:
      return {
        "opencodeId": model_id,
        "tokensPerSecond": None,
        "tokens": None,
        "error": ("Could not time generation: the gateway returned the whole completion at once, "
                  "so there is no generation window to measure. AA's published figure is used instead."),
      }
    result: dict[str, Any] = {
      "opencodeId": model_id,
      "tokensPerSecond": round(_median([float(sample["tps"]) for sample in usable])),
      "tokens": round(_median([float(sample["tokens"]) for sample in usable])),
      "samplesUsed": len(usable),
      "samplesTotal": len(samples),
    }
    if len(usable) < len(samples):
      result["note"] = f"{len(samples) - len(usable)} of {len(samples)} samples arrived buffered and were discarded"
    return result
  except urllib.error.HTTPError as error:
    return {"opencodeId": model_id, "tokensPerSecond": None, "tokens": None, "error": f"endpoint returned {error.code}"}
  except Exception as error:  # noqa: BLE001 - per-row failure never aborts the sweep
    return {"opencodeId": model_id, "tokensPerSecond": None, "tokens": None, "error": str(error)}


def probe_speed(model_ids: list[str]) -> list[dict[str, Any]]:
  auth = store.opencode_key()
  if not auth:
    return [{
      "opencodeId": model_id,
      "tokensPerSecond": None,
      "tokens": None,
      "error": "No opencode API key found. Sign in to opencode, or set OPENCODE_API_KEY.",
    } for model_id in model_ids]
  # Serial on purpose: running every model at once would have them competing for
  # the same subscription quota and each measurement would be wrong.
  return [probe_model(auth[0], model_id) for model_id in model_ids]
