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

import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import complete as complete_mod
from . import omniscience, opencode, store

CONCURRENCY = 8
ANSWER_MAX_TOKENS = 300

# A free model cannot be trusted to grade itself, so grading is a separate paid
# model on the same subscription. Override with FFA_GRADER_MODEL.
GRADER_MODEL = os.environ.get("FFA_GRADER_MODEL", "mimo-v2.6-flash")

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


def _run_question(api_key: str, model: str, item: dict[str, Any]) -> str:
  if cancel_requested():
    raise _Cancelled("cancelled")
  prediction = complete_mod.complete(api_key, model, omniscience.answer_prompt(item), ANSWER_MAX_TOKENS)
  # An empty response is an explicit refusal in this benchmark, not a parse
  # failure, so it never reaches the grader.
  if not prediction.strip():
    return "D"
  verdict = complete_mod.complete(api_key, GRADER_MODEL, omniscience.grader_prompt(item, prediction), 8)
  return omniscience.parse_grade(verdict)


def run(limit: int | None = None) -> dict[str, Any]:
  clear_cancel()

  auth = store.opencode_key()
  if not auth:
    raise RuntimeError("No opencode API key found. Sign in to opencode, or set OPENCODE_API_KEY.")
  api_key = auth[0]

  free_models = opencode.filter_free(opencode.fetch_go_models())
  if not free_models:
    raise RuntimeError("No free models in the opencode Go catalogue right now.")

  all_questions = omniscience.fetch_questions()
  questions = all_questions[:limit] if limit else all_questions
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
    "message": f"Grading with {GRADER_MODEL}",
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
        grades = list(pool.map(lambda item: _run_question(api_key, free["id"], item), questions))

      scores = omniscience.score_grades(grades)
      store.push_eval_history({
        "opencodeId": free["id"],
        "index": round(scores["index"], 4),
        "accuracy": round(scores["accuracy"], 4),
        "hallucinationRate": round(scores["hallucinationRate"], 4),
        "answered": scores["answered"],
        "total": scores["total"],
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


def start(limit: int | None = None) -> dict[str, Any]:
  """Validate, then hand the run to a detached process.

  A full run is 2,400 LLM calls over 15-25 minutes. It cannot be a child of the
  panel's process: a shell reload, a panel close, or a plugin restart would kill
  it mid-flight, and there is no progress to show.
  """
  state = read_state()
  if state.get("running"):
    raise RuntimeError("An eval run is already in progress.")

  auth = store.opencode_key()
  if not auth:
    raise RuntimeError("No opencode API key found. Sign in to opencode, or set OPENCODE_API_KEY.")

  free_models = opencode.filter_free(opencode.fetch_go_models())
  if not free_models:
    raise RuntimeError("No free models in the opencode Go catalogue right now.")

  all_questions = omniscience.fetch_questions()
  questions = all_questions[:limit] if limit else all_questions
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
