"""Filesystem layout and credential resolution.

Ported from the `free-for-all` Paseo plugin's server/store.ts. The layout moved
out of ~/.paseo, because this no longer runs inside Paseo, and every write is
now atomic — the original wrote straight to the target, so a reader landing
mid-write saw truncated JSON.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

# OpenCode Go refuses requests without `x-opencode-session` — it cannot route
# them. One id per process also lets the gateway reuse the prompt cache across a
# run, which matters a lot when the same grader prompt goes out 600 times.
SESSION_ID = "ffa-" + uuid.uuid4().hex[:8]

USER_AGENT = "opencode-go-watcher-free-for-all/1.0"


def config_dir() -> Path:
  return Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")) / "opencode-go-watcher"


def data_dir() -> Path:
  root = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")) / "opencode-go-watcher"
  directory = root / "free-for-all"
  directory.mkdir(parents=True, exist_ok=True)
  return directory


def settings_path() -> Path:
  return config_dir() / "settings.json"


def write_json(path: Path, payload: Any, mode: int = 0o644) -> None:
  """Atomic: temp file in the same directory, then rename.

  Every consumer here is a file watcher or a reader that can fire at any
  moment, and a half-written JSON file is indistinguishable from corruption.
  """
  path.parent.mkdir(parents=True, exist_ok=True)
  handle, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
  tmp = Path(tmp_name)
  try:
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
      fh.write(json.dumps(payload, indent=2) + "\n")
    tmp.chmod(mode)
    tmp.replace(path)
  except BaseException:
    tmp.unlink(missing_ok=True)
    raise


def read_json(path: Path) -> Any | None:
  try:
    return json.loads(path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError):
    return None


def read_settings() -> dict[str, str]:
  parsed = read_json(settings_path())
  if not isinstance(parsed, dict):
    return {}
  return {k: v for k, v in ((k, parsed.get(k)) for k in ("aaApiKey", "opencodeApiKey")) if isinstance(v, str) and v}


def write_settings(patch: dict[str, str]) -> None:
  # 0600: this file holds the Artificial Analysis key. The original set the mode
  # on create only, so an edit to an existing file left it world-readable.
  write_json(settings_path(), {**read_settings(), **patch}, mode=0o600)


def aa_api_key() -> str:
  return read_settings().get("aaApiKey") or os.environ.get("AA_API_KEY", "").strip()


def opencode_key() -> tuple[str, str] | None:
  """Resolution order, most explicit first.

  The auth.json fallback means a user who already talks to opencode-go from
  their shell does not have to paste anything.
  """
  stored = read_settings().get("opencodeApiKey")
  if stored:
    return stored, "watcher settings"

  env = os.environ.get("OPENCODE_API_KEY", "").strip()
  if env:
    return env, "OPENCODE_API_KEY"

  auth_path = (Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share"))
               / "opencode" / "auth.json")
  auth = read_json(auth_path)
  if isinstance(auth, dict):
    for provider in ("opencode-go", "opencode"):
      entry = auth.get(provider)
      if isinstance(entry, dict) and isinstance(entry.get("key"), str) and entry["key"]:
        return entry["key"], f"opencode auth.json ({provider})"
  return None


def data_path(name: str) -> Path:
  return data_dir() / f"{name}.json"


def read_data(name: str) -> Any | None:
  return read_json(data_path(name))


def write_data(name: str, payload: Any) -> None:
  write_json(data_path(name), payload)


def read_eval_history() -> list[dict[str, Any]]:
  cached = read_data("eval-history")
  grades = cached.get("grades") if isinstance(cached, dict) else None
  return grades if isinstance(grades, list) else []


def push_eval_history(grade: dict[str, Any]) -> list[dict[str, Any]]:
  """Newest first, capped so the file cannot grow without bound."""
  next_grades = [grade, *read_eval_history()][:50]
  write_data("eval-history", {"grades": next_grades})
  return next_grades
