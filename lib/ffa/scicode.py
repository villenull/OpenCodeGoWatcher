"""SciCode: the problems, the prompt, and running a model's code against the tests.

This is the test Artificial Analysis runs for its SciCode score, done the same
way so the free models' numbers sit on the same axis as the orchestrators':

  * the 288 scored sub-problems of the test split (65 problems, 291 steps,
    less the three steps the official harness never asks for);
  * the scientist-annotated background prompt, unchanged;
  * each step sees the model's OWN code for the earlier steps of its problem,
    as `gencode.py` does, so a problem's steps run in order;
  * sub-problem scoring: a step passes when every one of its test cases does.

The tests compare against SciCode's numeric targets, a 1 GB HDF5 file, and
import the benchmark's own helpers (`scicode.parse.parse`,
`scicode.compare.cmp`), which are vendored unchanged in lib/scicode_support.

Model-written code runs under bubblewrap: no network, the home directory
hidden, only the Python environment, the helpers and the targets visible.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import resource
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from . import store

# Pinned so a dataset edit upstream can't silently change what a score means.
DATASET_REVISION = "4510f6a6aa27c43fad7b43da2c59602a86e88480"
DATASET_URL = ("https://huggingface.co/datasets/SciCode1/SciCode/resolve/"
               f"{DATASET_REVISION}/problems_{{split}}.jsonl")

# SciCode's authors host the targets on Google Drive, which has no stable
# direct-download URL. This Hugging Face copy is pinned and checksummed; the
# practice split's official solutions pass against it (see verify()).
H5_URL = ("https://huggingface.co/datasets/Srimadh/Scicode-test-data-h5/resolve/"
          "72c247d3a8410921b2e848e046d71ed63d9a0ddb/test_data.h5")
H5_SHA256 = "48b0272a88b17dbd29777c217e1b4fb2b019b92e11cc2add847409db9541b890"
H5_SIZE = 1_049_345_865

# What the problems import (plus h5py, which the targets need). matplotlib is
# for the one problem that imports mpl_toolkits.
PACKAGES = ("numpy", "scipy", "sympy", "h5py", "matplotlib")

# The steps gencode.py skips: their code is given, never generated or scored.
GIVEN_STEPS = {("13", 6), ("62", 1), ("76", 3)}
SCORED_STEPS = 288

# AA grades each step script with a 300-second timeout.
STEP_TIMEOUT = 300
# Model-written code is untrusted; this keeps a runaway allocation from taking
# the desktop down with it.
STEP_MEMORY_BYTES = 8 * 1024 ** 3

SUPPORT_DIR = Path(__file__).resolve().parent.parent / "scicode_support"

PROMPT_TEMPLATE = """PROBLEM DESCRIPTION:
You will be provided with problem steps along with background knowledge necessary for solving the problem. Your task will be to develop a Python solution focused on the next step of the problem-solving process.

PROBLEM STEPS AND FUNCTION CODE:
Here, you'll find the Python code for the initial steps of the problem-solving process. This code is integral to building the solution.

{problem_steps_str}

NEXT STEP - PROBLEM STEP AND FUNCTION HEADER:
This part will describe the next step in the problem-solving process. A function header will be provided, and your task is to develop the Python code for this next step based on the provided description and function header.

{next_step_str}

DEPENDENCIES:
Use only the following dependencies in your solution. Do not include these dependencies at the beginning of your code.

{dependencies}

RESPONSE GUIDELINES:
Now, based on the instructions and information provided above, write the complete and executable Python program for the next step in a single block.
Your response should focus exclusively on implementing the solution for the next step, adhering closely to the specified function header and the context provided by the initial steps.
Your response should NOT include the dependencies and functions of all previous steps. If your next step function calls functions from previous steps, please make sure it uses the headers provided without modification.
DO NOT generate EXAMPLE USAGE OR TEST CODE in your response. Please make sure your response python code in format of ```python```."""


# --------------------------------------------------------------------- files

def scicode_dir() -> Path:
  directory = store.data_dir() / "scicode"
  directory.mkdir(parents=True, exist_ok=True)
  return directory


def env_python() -> Path:
  return scicode_dir() / "env" / "bin" / "python"


def data_file() -> Path:
  return scicode_dir() / "test_data.h5"


def env_ready() -> bool:
  python = env_python()
  if not python.exists():
    return False
  probe = subprocess.run([str(python), "-c", "import " + ", ".join(PACKAGES)],
                         capture_output=True, timeout=120)
  return probe.returncode == 0


def data_ready() -> bool:
  path = data_file()
  return path.exists() and path.stat().st_size == H5_SIZE


def ensure_env(say: Callable[[str], None]) -> None:
  """A private virtualenv with the problems' dependencies, built once."""
  if env_ready():
    return
  say("Installing SciCode's Python packages (once, ~150 MB)")
  env_dir = scicode_dir() / "env"
  shutil.rmtree(env_dir, ignore_errors=True)
  subprocess.run([sys.executable, "-m", "venv", str(env_dir)], check=True, capture_output=True, timeout=300)
  result = subprocess.run([str(env_python()), "-m", "pip", "install", "--quiet", *PACKAGES],
                          capture_output=True, text=True, timeout=1800)
  if result.returncode != 0 or not env_ready():
    detail = (result.stderr or result.stdout).strip().splitlines()
    raise RuntimeError("Couldn't install SciCode's Python packages" + (f": {detail[-1][:160]}" if detail else ""))


def ensure_data(say: Callable[[str], None]) -> None:
  """SciCode's test targets: downloaded once, checked against a pinned hash."""
  if data_ready():
    return
  part = data_file().with_suffix(".h5.part")
  digest = hashlib.sha256()
  received = 0
  request = urllib.request.Request(H5_URL, headers={"user-agent": store.USER_AGENT})
  try:
    with urllib.request.urlopen(request, timeout=60) as response, open(part, "wb") as out:
      last_percent = -1
      while True:
        chunk = response.read(1 << 20)
        if not chunk:
          break
        out.write(chunk)
        digest.update(chunk)
        received += len(chunk)
        percent = received * 100 // H5_SIZE
        if percent != last_percent and percent % 5 == 0:
          say(f"Downloading SciCode's test data (once, 1 GB) · {percent}%")
          last_percent = percent
  except (urllib.error.URLError, OSError) as error:
    part.unlink(missing_ok=True)
    raise RuntimeError(f"Couldn't download SciCode's test data: {error}") from error
  if received != H5_SIZE or digest.hexdigest() != H5_SHA256:
    part.unlink(missing_ok=True)
    raise RuntimeError("SciCode's test data didn't match its checksum; nothing was kept.")
  part.replace(data_file())


def fetch_problems(split: str = "test") -> list[dict[str, Any]]:
  cached = scicode_dir() / f"problems_{split}.jsonl"
  if not cached.exists():
    request = urllib.request.Request(DATASET_URL.format(split=split), headers={"user-agent": store.USER_AGENT})
    try:
      with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
    except (urllib.error.URLError, OSError) as error:
      raise RuntimeError(f"Couldn't download the SciCode problems: {error}") from error
    tmp = cached.with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.replace(cached)
  return [json.loads(line) for line in cached.read_text(encoding="utf-8").splitlines() if line.strip()]


def scored_step_count(problems: list[dict[str, Any]]) -> int:
  return sum(1 for problem in problems for number in range(1, len(problem["sub_steps"]) + 1)
             if (problem["problem_id"], number) not in GIVEN_STEPS)


# -------------------------------------------------------------------- prompt

def extract_function_name(function_header: str) -> str:
  match = re.search(r"\bdef\s+(\w+)\s*\(", function_header) or re.search(r"\bclass\s+(\w+)\s*\(", function_header)
  if not match:
    raise ValueError("Function name or class name not found.")
  return match.group(1)


def get_function_from_code(code: str | None, name: str) -> str | None:
  """As SciCode's parse.get_function_from_code: the named def or class, or the
  whole text if it doesn't parse."""
  if code is None:
    return None
  try:
    for node in ast.walk(ast.parse(code)):
      if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name == name:
        return ast.unparse(node)
  except Exception:  # noqa: BLE001 - SciCode's own fallback
    return code
  return None


def extract_python_script(response: str) -> str:
  """As SciCode's models.extract_python_script, including dropping imports:
  the dependencies are prepended to every step file."""
  if "```" in response:
    if "```python" in response:
      script = response.split("```python")[1].split("```")[0]
    else:
      script = response.split("```")[1].split("```")[0]
  else:
    script = response
  return re.sub(r"^\s*(import .*|from .*\s+import\s+.*)", "", script, flags=re.MULTILINE)


def given_code(problem_id: str, number: int, problem: dict[str, Any]) -> str | None:
  text = (SUPPORT_DIR / "steps" / f"{problem_id}.{number}.txt").read_text(encoding="utf-8")
  return get_function_from_code(text, extract_function_name(problem["sub_steps"][number - 1]["function_header"]))


def build_prompt(problem: dict[str, Any], number: int, previous: list[str | None]) -> tuple[str, str]:
  """(prompt, the code that precedes the answer in its step file), exactly as
  gencode.py's generate_prompt_with_steps with background."""
  steps = problem["sub_steps"]
  lines: list[str] = []
  for index in range(number - 1):
    lines.append(steps[index]["step_description_prompt"] + "\n" + steps[index]["step_background"])
    lines.append(previous[index] or "")
    lines.append("------")
  current = steps[number - 1]
  next_step = [current["step_description_prompt"] + "\n" + current["step_background"],
               f"{current['function_header']}\n\n{current['return_line']}"]
  prompt = PROMPT_TEMPLATE.format(
    problem_steps_str="\n\n".join(lines[:-1]),
    next_step_str="\n\n".join(next_step),
    dependencies=problem["required_dependencies"],
  )
  prefix = f"{problem['required_dependencies']}\n" + "\n".join(code or "" for code in previous[:number - 1]) + "\n"
  return prompt, prefix


def test_script(problem: dict[str, Any], number: int, step_code: str) -> str:
  """As test_generated_code.py writes it: the step file, then the targets, then
  each test case."""
  step = problem["sub_steps"][number - 1]
  parts = [step_code, "\n\nfrom scicode.parse.parse import process_hdf5_to_tuple\n\n",
           f"targets = process_hdf5_to_tuple('{step['step_number']}', {len(step['test_cases'])})\n"]
  for index, case in enumerate(step["test_cases"]):
    parts.append(f"target = targets[{index}]\n\n")
    parts.extend(line + "\n" for line in case.split("\n"))
  return "".join(parts)


# --------------------------------------------------------------------- run

def _limit_memory() -> None:
  resource.setrlimit(resource.RLIMIT_AS, (STEP_MEMORY_BYTES, STEP_MEMORY_BYTES))


def run_test(script: str) -> str:
  """'pass', 'fail' or 'timeout'. The script runs sealed off: no network, the
  home directory replaced by an empty tmpfs, and only the environment, the
  helpers and the targets bound back in, read-only."""
  if not shutil.which("bwrap"):
    raise RuntimeError("bubblewrap (bwrap) is needed to run model-written code safely; install it with: omarchy pkg add bubblewrap")
  env_dir = scicode_dir() / "env"
  with tempfile.TemporaryDirectory(prefix="ogw-scicode-") as work:
    script_path = Path(work) / "step.py"
    script_path.write_text(script, encoding="utf-8")
    command = [
      "bwrap", "--ro-bind", "/", "/",
      "--tmpfs", str(Path.home()), "--tmpfs", "/run", "--tmpfs", "/tmp",
      "--ro-bind", str(env_dir), str(env_dir),
      "--ro-bind", str(SUPPORT_DIR), str(SUPPORT_DIR),
      "--ro-bind", str(data_file()), str(data_file()),
      "--bind", work, work,
      "--proc", "/proc", "--dev", "/dev",
      "--unshare-all", "--die-with-parent", "--new-session",
      "--chdir", work,
      "--setenv", "HOME", work,
      "--setenv", "PYTHONPATH", str(SUPPORT_DIR),
      "--setenv", "SCICODE_H5", str(data_file()),
      "--setenv", "MPLBACKEND", "Agg",
      "--setenv", "OMP_NUM_THREADS", "1",
      "--setenv", "OPENBLAS_NUM_THREADS", "1",
      str(env_python()), str(script_path),
    ]
    try:
      result = subprocess.run(command, capture_output=True, timeout=STEP_TIMEOUT,
                              stdin=subprocess.DEVNULL, preexec_fn=_limit_memory)
    except subprocess.TimeoutExpired:
      return "timeout"
  return "pass" if result.returncode == 0 else "fail"


def verify(say: Callable[[str], None] = print) -> tuple[int, int]:
  """Run the practice split's official solutions against the targets.

  They must all pass: that is the check that the downloaded targets, the
  vendored helpers and the sandbox add up to SciCode's own grader.
  """
  ensure_env(say)
  ensure_data(say)
  passed = total = 0
  for problem in fetch_problems("dev"):
    previous: list[str | None] = []
    for number, step in enumerate(problem["sub_steps"], start=1):
      code = step["ground_truth_code"]
      _, prefix = build_prompt(problem, number, previous)
      outcome = run_test(test_script(problem, number, f"{prefix}\n{code}"))
      total += 1
      passed += outcome == "pass"
      if outcome != "pass":
        say(f"  {step['step_number']}: {outcome}")
      previous.append(code)
  return passed, total
