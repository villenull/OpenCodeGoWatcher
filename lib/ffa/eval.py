"""The SciCode benchmark runner.

A run asks each free model for every scored SciCode step, runs the code it
writes against SciCode's tests, and records the share that pass — the number
Artificial Analysis publishes as SciCode for the paid models.

Run state is persisted to `eval-state.json` rather than held in memory, so a
run that outlives a plugin reload can still be watched and cancelled. A run
takes hours, so each model's finished steps are kept in
`scicode-progress-<model>.json`: an interrupted run picks up where it stopped
instead of starting over.
"""

from __future__ import annotations

import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from . import complete as complete_mod
from . import opencode, scicode, store

# Problems in flight at once. A problem's steps run in order (each sees the
# model's own code for the earlier ones), so problems are the unit of
# parallelism.
CONCURRENCY = 4

# Medium reasoning effort, for two reasons. The orchestrators on the chart are
# AA's medium-effort entries, and your OpenCode workers run the free models at
# medium. And without it the API's default thinks far longer: Space Bunny spent
# all of 16,000 tokens reasoning on a one-step problem and wrote no code, where
# at medium it answered in about a minute.
EFFORT = "medium"

# Room for a reasoning model to think and still write the code.
ANSWER_MAX_TOKENS = 32000
ANSWER_TIMEOUT = 900

RETRIES = 2

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
    # kill. Reporting "running" forever would be a lie, and the window's button
    # would refuse to start anything.
    return {
      **merged,
      "running": False,
      "message": "Run interrupted",
      "error": "The benchmark stopped before it finished. Run it again to continue where it left off.",
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


def _with_retries(call):
  """A slow or dropped request is common on free models; retry it before
  giving up, with a short pause between attempts."""
  for attempt in range(RETRIES + 1):
    if cancel_requested():
      raise _Cancelled("cancelled")
    try:
      return call()
    except (RuntimeError, OSError):
      if attempt == RETRIES:
        raise
      time.sleep(5 * (attempt + 1))
  raise AssertionError("unreachable")


def _chosen(free_models: list[dict[str, Any]], models: list[str] | None) -> list[dict[str, Any]]:
  """The free models to benchmark: all of them, or the ones named."""
  if models:
    free_models = [model for model in free_models if model["id"] in models]
    if not free_models:
      raise RuntimeError("None of those models is free on opencode Go right now: " + ", ".join(models))
  if not free_models:
    raise RuntimeError("No free models in the opencode Go catalogue right now.")
  return free_models


# ------------------------------------------------------------------ progress

def _progress_name(model_id: str) -> str:
  return f"scicode-progress-{model_id}"


def _load_progress(model_id: str) -> dict[str, dict[str, Any]]:
  """Finished steps from an earlier, interrupted run of this model:
  {step_number: {"status": pass|fail|timeout|skipped, "code": str|None}}."""
  saved = store.read_data(_progress_name(model_id))
  if (isinstance(saved, dict) and saved.get("dataset") == scicode.DATASET_REVISION
      and isinstance(saved.get("steps"), dict)):
    return saved["steps"]
  return {}


def _save_progress(model_id: str, steps: dict[str, dict[str, Any]]) -> None:
  store.write_data(_progress_name(model_id), {"dataset": scicode.DATASET_REVISION, "steps": steps})


def _clear_progress(model_id: str) -> None:
  store.data_path(_progress_name(model_id)).unlink(missing_ok=True)


# ----------------------------------------------------------------------- run

def _run_problem(api_key: str, model_id: str, problem: dict[str, Any],
                 done: dict[str, dict[str, Any]], record) -> None:
  """Every step of one problem, in order.

  A step whose request keeps failing is "skipped", and so is the rest of its
  problem: the later steps would be asked to build on code that doesn't
  exist, which would score the network, not the model. Skipped steps are left
  out of the score and reported.
  """
  problem_id = problem["problem_id"]
  previous: list[str | None] = []
  broken = False
  for number, step in enumerate(problem["sub_steps"], start=1):
    if (problem_id, number) in scicode.GIVEN_STEPS:
      previous.append(scicode.given_code(problem_id, number, problem))
      continue
    key = step["step_number"]
    if key in done:
      previous.append(done[key].get("code"))
      continue
    if broken:
      record(key, "skipped", None)
      previous.append(None)
      continue

    prompt, prefix = scicode.build_prompt(problem, number, previous)
    try:
      response = _with_retries(lambda: complete_mod.complete(
        api_key, model_id, prompt, ANSWER_MAX_TOKENS, timeout=ANSWER_TIMEOUT, effort=EFFORT))
    except (RuntimeError, OSError):
      broken = True
      record(key, "skipped", None)
      previous.append(None)
      continue

    code = scicode.extract_python_script(response)
    status = scicode.run_test(scicode.test_script(problem, number, f"{prefix}\n{code}"))
    record(key, status, code)
    previous.append(code)


def score(steps: dict[str, dict[str, Any]]) -> dict[str, Any]:
  passed = sum(1 for step in steps.values() if step["status"] == "pass")
  skipped = sum(1 for step in steps.values() if step["status"] == "skipped")
  attempted = len(steps) - skipped
  return {
    "score": (passed / attempted) if attempted else 0.0,
    "passed": passed,
    "attempted": attempted,
    "skipped": skipped,
  }


def run(models: list[str] | None = None) -> dict[str, Any]:
  clear_cancel()
  # Counters start from zero here, not from whatever the last run left: `run`
  # can be called without `start` (tests, or the CLI's internal verb).
  state = {**read_state(), "running": True, "pid": os.getpid(), "error": None,
           "progress": 0.0, "currentQuestion": 0, "totalQuestions": None, "finishedAt": None}
  write_state(state)

  def say(message: str) -> None:
    nonlocal state
    state = {**state, "message": message}
    write_state(state)

  try:
    auth = store.opencode_key()
    if not auth:
      raise RuntimeError("No opencode API key found. Sign in to opencode, or set OPENCODE_API_KEY.")
    api_key = auth[0]
    free_models = _chosen(opencode.filter_free(opencode.fetch_go_models()), models)

    scicode.ensure_env(say)
    scicode.ensure_data(say)
    problems = scicode.fetch_problems("test")
    per_model = scicode.scored_step_count(problems)
    total = per_model * len(free_models)

    lock = Lock()
    finished = 0

    for model_index, free in enumerate(free_models):
      done = _load_progress(free["id"])
      finished += len(done)
      state = {**state, "totalQuestions": total, "currentQuestion": finished, "progress": finished / total}
      say(f"SciCode · {free['label']} ({model_index + 1}/{len(free_models)})")

      def record(key: str, status: str, code: str | None, model_id: str = free["id"],
                 steps: dict[str, dict[str, Any]] = done) -> None:
        nonlocal finished, state
        with lock:
          steps[key] = {"status": status, "code": code}
          _save_progress(model_id, steps)
          finished += 1
          state = {**state, "currentQuestion": finished, "progress": finished / total}
          write_state(state)

      with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = [pool.submit(_run_problem, api_key, free["id"], problem, done, record) for problem in problems]
        for future in futures:
          future.result()

      result = score(done)
      if result["attempted"] == 0:
        raise RuntimeError(f"{free['label']} answered none of the SciCode steps.")
      store.push_scicode_history({
        "opencodeId": free["id"],
        "score": round(result["score"], 4),
        "passed": result["passed"],
        "attempted": result["attempted"],
        "skipped": result["skipped"],
        "total": per_model,
        "effort": EFFORT,
        "finishedAt": now_iso(),
      })
      _clear_progress(free["id"])

    write_state({**state, "running": False, "progress": 1.0, "finishedAt": now_iso(),
                 "message": "Run complete", "pid": None})
  except _Cancelled:
    write_state({**state, "running": False, "message": "Cancelled",
                 "error": "Run cancelled. Run it again to continue where it left off.",
                 "finishedAt": now_iso(), "pid": None})
  except Exception as error:  # noqa: BLE001 - reported in the window, not raised
    write_state({**state, "running": False, "message": "Run failed", "error": str(error),
                 "finishedAt": now_iso(), "pid": None})

  return read_state()


def start(models: list[str] | None = None) -> dict[str, Any]:
  """Validate, then hand the run to a detached process.

  A run is hours of LLM calls and test runs. It cannot be a child of the
  window's process: a shell reload, a window close, or a plugin restart would
  kill it mid-flight.
  """
  state = read_state()
  if state.get("running"):
    raise RuntimeError("A SciCode run is already in progress.")

  if not store.opencode_key():
    raise RuntimeError("No opencode API key found. Sign in to opencode, or set OPENCODE_API_KEY.")
  _chosen(opencode.filter_free(opencode.fetch_go_models()), models)

  run_id = "run-" + format(int(time.time()), "x")
  clear_cancel()
  write_state({
    **IDLE_STATE,
    "running": True,
    "runId": run_id,
    "progress": 0.0,
    "currentQuestion": 0,
    "startedAt": now_iso(),
    "message": "Starting…",
  })

  plugin_root = Path(__file__).resolve().parent.parent.parent
  runner = plugin_root / "bin" / "opencode-go-watcher-free-for-all-eval"
  log_path = store.data_dir() / "eval.log"
  args = [str(runner), "run"]
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
  return {"runId": run_id, "pid": process.pid}
