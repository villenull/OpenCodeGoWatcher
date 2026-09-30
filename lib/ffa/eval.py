"""The Omniscience eval runner.

Ported from server/eval.ts, with two corrections:

  * Run state is persisted to `eval-state.json` instead of living in a module
    global. The original kept it in memory, so a run that outlived a plugin
    reload had nobody left to report it — it would keep spending 2,400 calls
    with no progress anyone could see and no way to cancel it.
  * `currentQuestion` counts every question graded across every model, not the
    per-model index. The original compared a per-model counter against a global
    total, so the readout walked 1/1200 … 600/1200 and then jumped back to
    1/1200 for the next model.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import complete as complete_mod
from . import omniscience, opencode, store

CONCURRENCY = 4
ANSWER_MAX_TOKENS = 300

# A free model cannot be trusted to grade itself, so grading is Big Pickle on
# OpenCode Zen: free, but rate-limited per day, and Zen's free tier only
# answers requests made from OpenCode itself — so grades go through the
# `opencode` CLI rather than the HTTP API. Override with FFA_GRADER_MODEL
# (an `opencode run -m` model id).
GRADER_MODEL = os.environ.get("FFA_GRADER_MODEL", "opencode/big-pickle")
GRADER_TIMEOUT = 180

# A run grades DEFAULT_QUESTIONS of the 600 public questions per free model,
# which keeps it inside Big Pickle's daily allowance. `start 600` runs them all.
DEFAULT_QUESTIONS = 100

IDLE_STATE: dict[str, Any] = {
  "running": False,
  "runId": None,
  "progress": None,
  "currentQuestion": None,
  "totalQuestions": None,
  "startedAt": None,
  "finishedAt": None,
  "message": None,
  "error": None,
  "pid": None,
}


def now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: Any) -> bool:
  if not isinstance(pid, int) or pid <= 0:
    return False
  try:
    os.kill(pid, 0)
  except ProcessLookupError:
    return False
  except PermissionError:
    return True
  return True


def read_state() -> dict[str, Any]:
  state = store.read_data("eval-state")
  if not isinstance(state, dict):
    return dict(IDLE_STATE)

  merged = {**IDLE_STATE, **state}
  if merged.get("running") and not _pid_alive(merged.get("pid")):
    # The runner died without writing a terminal state — a reboot, an OOM, or a
    # kill. Reporting "running" forever would be a lie, and the panel's Run
    # button would refuse to start anything.
    return {
      **merged,
      "running": False,
      "message": "Run interrupted",
      "error": "The eval process is no longer running. Its last results were kept.",
      "finishedAt": merged.get("finishedAt") or now_iso(),
    }
  return merged


def write_state(state: dict[str, Any]) -> None:
  store.write_data("eval-state", state)


def cancel_requested() -> bool:
  return store.data_path("eval-cancel").exists()


def request_cancel() -> None:
  store.data_path("eval-cancel").parent.mkdir(parents=True, exist_ok=True)
  store.data_path("eval-cancel").write_text(now_iso() + "\n", encoding="utf-8")


def clear_cancel() -> None:
  store.data_path("eval-cancel").unlink(missing_ok=True)


class _Cancelled(RuntimeError):
  pass


def sample_questions(questions: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
  """An even stride through the set rather than its first N, so a short run
  still covers every domain instead of just the first few."""
  if not limit or limit >= len(questions):
    return questions
  step = len(questions) / limit
  return [questions[int(index * step)] for index in range(limit)]


def _opencode_bin() -> str:
  # The panel's process may not have mise's shims on PATH.
  return shutil.which("opencode") or str(Path.home() / ".local" / "share" / "mise" / "shims" / "opencode")


def grade(prompt: str) -> str:
  """One verdict from the grader, via `opencode run`.

  Read-only agent, empty scratch directory, no plugins: the grader only has to
  read the prompt, and nothing in a question should be able to make it touch
  files or run commands.
  """
  with tempfile.TemporaryDirectory(prefix="ogw-grade-") as scratch:
    result = subprocess.run(
      [_opencode_bin(), "run", "--pure", "--agent", "plan", "--format", "json", "-m", GRADER_MODEL, prompt],
      cwd=scratch, capture_output=True, text=True, timeout=GRADER_TIMEOUT, stdin=subprocess.DEVNULL,
    )
  text = []
  for line in result.stdout.splitlines():
    try:
      event = json.loads(line)
    except ValueError:
      continue
    part = event.get("part") if isinstance(event, dict) else None
    if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
      text.append(part["text"])
  if not text:
    detail = (result.stderr or result.stdout).strip().splitlines()
    raise RuntimeError(f"{GRADER_MODEL} gave no verdict" + (f": {detail[-1][:160]}" if detail else ""))
  return "".join(text)


RETRIES = 2


def _with_retries(call):
  """A slow or dropped request is common on free models; retry it before
  giving up, with a short pause between attempts."""
  for attempt in range(RETRIES + 1):
    if cancel_requested():
      raise _Cancelled("cancelled")
    try:
      return call()
    except (RuntimeError, OSError, subprocess.TimeoutExpired):
      if attempt == RETRIES:
        raise
      time.sleep(2 * (attempt + 1))
  raise AssertionError("unreachable")


def _run_question(api_key: str, model: str, item: dict[str, Any]) -> str | None:
  """A grade, or None when the model never answered — that question is left
  out of the score rather than failing the whole model. A grader that keeps
  failing (Big Pickle's daily limit, say) still raises: nothing can be graded."""
  try:
    prediction = _with_retries(
      lambda: complete_mod.complete(api_key, model, omniscience.answer_prompt(item), ANSWER_MAX_TOKENS))
  except (RuntimeError, OSError):
    return None
  # An empty response is an explicit refusal in this benchmark, not a parse
  # failure, so it never reaches the grader.
  if not prediction.strip():
    return "D"
  return omniscience.parse_grade(_with_retries(lambda: grade(omniscience.grader_prompt(item, prediction))))


def _chosen(free_models: list[dict[str, Any]], models: list[str] | None) -> list[dict[str, Any]]:
  """The free models to grade: all of them, or the ones named."""
  if models:
    free_models = [model for model in free_models if model["id"] in models]
    if not free_models:
      raise RuntimeError("None of those models is free on opencode Go right now: " + ", ".join(models))
  if not free_models:
    raise RuntimeError("No free models in the opencode Go catalogue right now.")
  return free_models


def run(limit: int | None = None, models: list[str] | None = None) -> dict[str, Any]:
  clear_cancel()

  auth = store.opencode_key()
  if not auth:
    raise RuntimeError("No opencode API key found. Sign in to opencode, or set OPENCODE_API_KEY.")
  api_key = auth[0]

  free_models = _chosen(opencode.filter_free(opencode.fetch_go_models()), models)

  questions = sample_questions(omniscience.fetch_questions(), limit or DEFAULT_QUESTIONS)
  run_id = "run-" + format(int(time.time()), "x")
  total = len(questions) * len(free_models)

  state: dict[str, Any] = {
    **IDLE_STATE,
    "running": True,
    "runId": run_id,
    "progress": 0.0,
    "currentQuestion": 0,
    "totalQuestions": total,
    "startedAt": now_iso(),
    "message": f"Grading with {GRADER_MODEL.split('/')[-1]}",
    "pid": os.getpid(),
  }
  write_state(state)

  done = 0

  def bump() -> None:
    nonlocal done, state
    done += 1
    state = {**state, "progress": done / total, "currentQuestion": done}
    write_state(state)

  try:
    for model_index, free in enumerate(free_models):
      state = {**state, "message": f"Answering with {free['label']} ({model_index + 1}/{len(free_models)})"}
      write_state(state)

      # One worker thread per question, capped: each is two blocking HTTP calls,
      # so this is I/O concurrency and threads are the right tool.
      with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        def graded(item: dict[str, Any], model_id: str = free["id"]) -> str | None:
          verdict = _run_question(api_key, model_id, item)
          bump()
          return verdict
        grades = list(pool.map(graded, questions))

      graded_only = [verdict for verdict in grades if verdict is not None]
      if not graded_only:
        raise RuntimeError(f"{free['label']} answered none of the questions.")
      scores = omniscience.score_grades(graded_only)
      store.push_eval_history({
        "opencodeId": free["id"],
        "index": round(scores["index"], 4),
        "accuracy": round(scores["accuracy"], 4),
        "hallucinationRate": round(scores["hallucinationRate"], 4),
        "answered": scores["answered"],
        "total": scores["total"],
        "skipped": len(grades) - len(graded_only),
        "finishedAt": now_iso(),
      })

    write_state({
      **state,
      "running": False,
      "progress": 1.0,
      "currentQuestion": total,
      "finishedAt": now_iso(),
      "message": "Run complete",
      "pid": None,
    })
  except _Cancelled:
    write_state({**state, "running": False, "message": "Cancelled", "error": "Run cancelled.",
                 "finishedAt": now_iso(), "pid": None})
  except Exception as error:  # noqa: BLE001 - reported in the panel, not raised
    write_state({**state, "running": False, "message": "Run failed", "error": str(error),
                 "finishedAt": now_iso(), "pid": None})

  return read_state()


def start(limit: int | None = None, models: list[str] | None = None) -> dict[str, Any]:
  """Validate, then hand the run to a detached process.

  A default run is 400 LLM calls over several minutes. It cannot be a child of the
  panel's process: a shell reload, a panel close, or a plugin restart would kill
  it mid-flight, and there is no progress to show.
  """
  state = read_state()
  if state.get("running"):
    raise RuntimeError("An eval run is already in progress.")

  auth = store.opencode_key()
  if not auth:
    raise RuntimeError("No opencode API key found. Sign in to opencode, or set OPENCODE_API_KEY.")

  free_models = _chosen(opencode.filter_free(opencode.fetch_go_models()), models)

  questions = sample_questions(omniscience.fetch_questions(), limit or DEFAULT_QUESTIONS)
  total = len(questions) * len(free_models)
  run_id = "run-" + format(int(time.time()), "x")

  clear_cancel()
  write_state({
    **IDLE_STATE,
    "running": True,
    "runId": run_id,
    "progress": 0.0,
    "currentQuestion": 0,
    "totalQuestions": total,
    "startedAt": now_iso(),
    "message": "Starting…",
  })

  plugin_root = Path(__file__).resolve().parent.parent.parent
  runner = plugin_root / "bin" / "opencode-go-watcher-free-for-all-eval"
  log_path = store.data_dir() / "eval.log"
  args = [str(runner), "run"] + ([str(limit)] if limit else [])
  for model_id in models or []:
    args += ["--model", model_id]

  with open(log_path, "ab", buffering=0) as log:
    process = subprocess.Popen(
      args,
      stdout=log,
      stderr=subprocess.STDOUT,
      stdin=subprocess.DEVNULL,
      start_new_session=True,
      cwd=str(plugin_root),
    )

  state = read_state()
  write_state({**state, "pid": process.pid})
  return {"runId": run_id, "totalQuestions": total, "pid": process.pid}
