"""One completion against an OpenCode Go model, in whatever protocol it speaks.

Ported from server/complete.ts.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from . import store

GO_BASE = "https://opencode.ai/zen/go/v1"


def protocol_for(model: str) -> str:
  """OpenCode Go fronts three upstream wire formats and a model only accepts
  the one it was published with. Guessing wrong gets a 400
  ModelProtocolUnsupported, which is exactly what happened to gpt-6-luna as a
  grader."""
  model_id = model.lower()
  if model_id.startswith(("gpt", "o1", "o3", "o4")) or model_id.startswith("grok"):
    return "responses"
  if model_id.startswith("minimax") or model_id.startswith("muse-spark"):
    return "messages"
  return "chat"


def endpoint_for(model: str) -> str:
  protocol = protocol_for(model)
  if protocol == "responses":
    return f"{GO_BASE}/responses"
  if protocol == "messages":
    return f"{GO_BASE}/messages"
  return f"{GO_BASE}/chat/completions"


def _text_parts(parts: Any) -> str:
  if not isinstance(parts, list):
    return ""
  return "".join(part["text"] for part in parts
                 if isinstance(part, dict) and isinstance(part.get("text"), str))


def extract_text(protocol: str, body: Any) -> str:
  root = body if isinstance(body, dict) else {}

  if isinstance(root.get("output_text"), str) and root["output_text"]:
    return root["output_text"]

  if protocol == "messages":
    content = root.get("content")
    if isinstance(content, list):
      return "".join(part["text"] for part in content
                     if isinstance(part, dict) and part.get("type") == "text"
                     and isinstance(part.get("text"), str)).strip()

  if protocol == "responses":
    output = root.get("output")
    if isinstance(output, list):
      collected = []
      for item in output:
        if isinstance(item, dict) and isinstance(item.get("content"), list):
          collected.extend(item["content"])
      return _text_parts(collected).strip()

  choices = root.get("choices")
  choice = choices[0] if isinstance(choices, list) and choices else None
  if isinstance(choice, dict):
    message = choice.get("message")
    text = message.get("content") if isinstance(message, dict) else choice.get("text")
    if isinstance(text, str):
      return text.strip()
  return ""


def _build_body(protocol: str, model: str, prompt: str, max_tokens: int) -> dict[str, Any]:
  if protocol == "responses":
    return {"model": model, "input": prompt, "max_output_tokens": max_tokens}
  # `messages` and `chat` happen to share a body shape here; kept as two
  # branches so a future divergence is a one-line change.
  return {
    "model": model,
    "max_tokens": max_tokens,
    "messages": [{"role": "user", "content": prompt}],
  }


def complete(api_key: str, model: str, prompt: str, max_tokens: int, timeout: int = 120) -> str:
  protocol = protocol_for(model)
  request = urllib.request.Request(
    endpoint_for(model),
    data=json.dumps(_build_body(protocol, model, prompt, max_tokens)).encode("utf-8"),
    headers={
      "authorization": f"Bearer {api_key}",
      "content-type": "application/json",
      "user-agent": store.USER_AGENT,
      "x-opencode-session": store.SESSION_ID,
    },
    method="POST",
  )
  try:
    with urllib.request.urlopen(request, timeout=timeout) as response:
      return extract_text(protocol, json.load(response))
  except urllib.error.HTTPError as error:
    detail = ""
    try:
      detail = error.read().decode("utf-8", "replace")[:140]
    except Exception:  # noqa: BLE001 - the status alone is the useful part
      pass
    suffix = f": {detail}" if detail else ""
    raise RuntimeError(f"{model} returned {error.code}{suffix}") from error
  except Exception as error:  # noqa: BLE001 - re-raised with the model named
    raise RuntimeError(f"{model} request failed: {error}") from error
