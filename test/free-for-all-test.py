#!/usr/bin/python3
"""Pins the free-for-all logic ported out of the Paseo plugin.

Three things here are easy to get subtly wrong and expensive to get wrong:

  * the fuzzy join, because a wrong match publishes a fabricated benchmark
    number as though it were real;
  * the SciCode prompt and step files, because a drift from the official
    harness makes our score incomparable with the one AA publishes;
  * the run's progress, skipping and resuming, and the speed timing, which
    once reported reasoning models several times too fast.

No network. The fetchers are replaced with fixtures, so the suite passes on a
machine with no keys and no subscription.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from ffa import aaweb, complete, dashboard, eval as eval_mod, match, opencode, scicode, speed, store  # noqa: E402

PASSED = 0
FAILED = 0

# Every path under the plugin's state directory is redirected into a temp dir for
# the whole run. The dashboard and eval code both end in a real
# `store.write_data`, so without this the suite writes fixtures over the user's
# own snapshot and the window then cheerfully renders "Model 30" as if it were a
# leaderboard.
SANDBOX = tempfile.TemporaryDirectory()
_real_data_dir = store.data_dir
# A real run leaves eval-state.json behind, so "the tests didn't write there" is
# checked against its state before they ran, not against its absence.
_real_state = _real_data_dir() / "eval-state.json"
_real_state_before = _real_state.stat().st_mtime_ns if _real_state.exists() else None
store.data_dir = lambda: Path(SANDBOX.name)


def check(label: str, expected: object, actual: object) -> None:
  global PASSED, FAILED
  if expected == actual:
    PASSED += 1
    print(f"  ok   {label}")
  else:
    FAILED += 1
    print(f"  FAIL {label}\n       expected [{expected!r}], got [{actual!r}]")


def section(name: str) -> None:
  print(name)


# --------------------------------------------------------------- opencode.py

section("opencode: catalogue helpers")
check("a numeric segment is not capitalised", "Longcat 2.5 Preview Free", opencode.prettify("longcat-2.5-preview-free"))
check("a word segment is", "Space Bunny Free", opencode.prettify("space-bunny-free"))
check("the -free suffix means free", True, opencode.is_free_id("space-bunny-free"))
check("big-pickle is free by exception", True, opencode.is_free_id("big-pickle"))
check("a paid model is not free", False, opencode.is_free_id("gpt-6-astra"))
check("the suffix is a suffix, not a substring", False, opencode.is_free_id("free-tier-model"))
check("unknown models warn about training", True, "may be used" in opencode.TRAINING_RISK)
check("space-bunny-free is zero-retention", "stealth model · zero-retention, no training", opencode.NOTES["space-bunny-free"])


# ------------------------------------------------------------------ match.py

section("match: joining opencode ids to AA slugs")
CATALOGUE = [
  {"name": "Space Bunny", "slug": "space-bunny", "intelligence": 42.0, "tokensPerSecond": 90.0},
  {"name": "LongCat 2.0", "slug": "longcat-2-0", "intelligence": 30.0, "tokensPerSecond": 70.0},
  {"name": "LongCat 2.5 Preview", "slug": "longcat-2-5-preview", "intelligence": 50.0, "tokensPerSecond": 80.0},
  {"name": "HY 3", "slug": "hy3", "intelligence": 20.0, "tokensPerSecond": 60.0},
  {"name": "MiniCPM5 2B", "slug": "minicpm5-2b", "intelligence": 10.0, "tokensPerSecond": 50.0},
]

check("the free marker is stripped before matching", "exact", match.match_aa_model("space-bunny-free", CATALOGUE)["method"])
check("and it finds the right model", "space-bunny", match.match_aa_model("space-bunny-free", CATALOGUE)["model"]["slug"])
check("a version bump is a different model", "longcat-2-5-preview",
      match.match_aa_model("longcat-2.5-preview-free", CATALOGUE)["model"]["slug"])
check("which means 2.5 does not inherit 2.0", True,
      match.match_aa_model("longcat-2.5-preview-free", CATALOGUE)["model"]["slug"] != "longcat-2-0")
check("a partial slug matches by containment", "space-bunny",
      match.match_aa_model("space-bunny-preview-free", CATALOGUE)["model"]["slug"])
check("but a mere rearrangement does not", None, match.match_aa_model("hy-3", CATALOGUE))
check("a short id matches itself exactly", "exact", match.match_aa_model("hy3", CATALOGUE)["method"])
check("and never latches onto a longer model", "hy3", match.match_aa_model("hy3", CATALOGUE)["model"]["slug"])
check("a stealth model matches nothing", None, match.match_aa_model("space-bunny", []))
check("versions must agree before containment", False, match.versions_agree("longcat-2-5", "longcat-2-0"))
check("no version on one side is not a conflict", True, match.versions_agree("claude", "gpt-6"))
check("a bare version segment still counts as one", True, match.versions_agree("muse-spark", "muse-spark-1-3"))


# --------------------------------------------------------------- complete.py

section("complete: protocol selection and text extraction")
check("gpt speaks the responses protocol", "responses", complete.protocol_for("gpt-6-astra"))
check("o-series too", "responses", complete.protocol_for("o3-mini"))
check("grok too", "responses", complete.protocol_for("grok-4"))
check("minimax speaks messages", "messages", complete.protocol_for("minimax-m2"))
check("muse-spark speaks messages", "messages", complete.protocol_for("muse-spark-1.3"))
check("everything else is chat", "chat", complete.protocol_for("mimo-v2.6-flash"))
check("the grader resolves to chat", True, complete.endpoint_for("mimo-v2.6-flash").endswith("/chat/completions"))
check("responses uses its own endpoint", "/responses", complete.endpoint_for("gpt-6-astra").split("/v1")[1])

check("output_text is preferred", "hi", complete.extract_text("responses", {"output_text": "hi"}))
check("responses output is walked", "ab", complete.extract_text(
  "responses", {"output": [{"content": [{"text": "a"}, {"text": "b"}]}]}))
check("messages content is joined", "ab", complete.extract_text(
  "messages", {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}))
check("non-text message parts are skipped", "a", complete.extract_text(
  "messages", {"content": [{"type": "image"}, {"type": "text", "text": "a"}]}))
check("chat choices are read", "hey", complete.extract_text(
  "chat", {"choices": [{"message": {"content": " hey "}}]}))
check("chat sends effort as reasoning_effort", "medium",
      complete._build_body("chat", "space-bunny-free", "p", 10, "medium")["reasoning_effort"])
check("responses sends it as reasoning.effort", {"effort": "medium"},
      complete._build_body("responses", "gpt-6-astra", "p", 10, "medium")["reasoning"])
check("no effort sends nothing extra", False, "reasoning_effort" in complete._build_body("chat", "m", "p", 10))
check("messages has no effort field", False, "reasoning_effort" in complete._build_body("messages", "minimax-m2", "p", 10, "medium"))
check("an empty body is empty text", "", complete.extract_text("chat", {}))
check("a null body is empty text", "", complete.extract_text("chat", None))
check("a missing message does not raise", "", complete.extract_text("chat", {"choices": [{}]}))


# ----------------------------------------------------- dashboard: AA variants

section("dashboard: which effort a number came from")
check("max effort is the default and is not restated", "", dashboard.config_label("GPT-6 Astra (max)"))
check("AA's long form reduces to the effort", "medium",
      dashboard.config_label("Claude Opus 5.5 (Adaptive Reasoning, Medium Effort, Default Fallback)"))
check("max in the long form says nothing", "",
      dashboard.config_label("Claude Opus 5.5 (Adaptive Reasoning, Max Effort, Default Fallback)"))
check("a short form is read too", "medium", dashboard.config_label("GPT-6.1 Sol (medium)"))
check("xhigh is not mistaken for high", "xhigh", dashboard.config_label("GPT-6 Astra (xhigh)"))
check("a model with no parenthetical has no config", "", dashboard.config_label("Celeris-1"))
check("an unrelated bracket is not a config", "", dashboard.config_label("Gemma 3 [2B]"))
check("a size is not an effort", "", dashboard.config_label("Meta Spark (3.3B max)"))

section("dashboard: AA's top models for context")
def record(slug, name, release, intelligence, deprecated=False, speed=None, sci=None):
  return {"slug": slug, "name": name, "releaseSlug": release, "intelligence": intelligence,
          "tokensPerSecond": speed, "scicode": sci, "deprecated": deprecated}

VARIANTS = [
  record("opus-max", "Claude Opus 5.5 (Adaptive Reasoning, Max Effort)", "opus", 57.6),
  record("opus-xhigh", "Claude Opus 5.5 (Adaptive Reasoning, Xhigh Effort)", "opus", 58.0),
  record("astra-max", "GPT-6 Astra (max)", "astra", 52.7),
  record("astra-xhigh", "GPT-6 Astra (xhigh)", "astra", 52.4),
  record("old", "Claude Opus 5 (max)", "opus-5", 60.0, deprecated=True),
  record("celeris", "Celeris-1", "celeris", 50.0),
  record("blank", "Blank (max)", "blank", None),
]
top = dashboard._top_context(VARIANTS, set())
check("one entry per release", 3, len(top))
check("the max entry beats a higher non-max score", "opus-max", top[0]["slug"])
check("retired models are left out", False, any(m["slug"] == "old" for m in top))
check("a model without a score is left out", False, any(m["slug"] == "blank" for m in top))
check("sorted by intelligence", ["opus-max", "astra-max", "celeris"], [m["slug"] for m in top])
check("an orchestrator's release is not repeated as context", ["astra-max", "celeris"],
      [m["slug"] for m in dashboard._top_context(VARIANTS, {"opus"})])
many = [record(f"m{n}", f"Model {n} (max)", f"m{n}", float(n)) for n in range(20)]
check("capped at TOP_CONTEXT", dashboard.TOP_CONTEXT, len(dashboard._top_context(many, set())))


# ----------------------------------------------------------------- aaweb.py

section("aaweb: records from AA's page payload")
def rsc(payload: str) -> str:
  escaped = payload.replace("\\", "\\\\").replace('"', '\\"')
  return f'<script>self.__next_f.push([1,"{escaped}"])</script>'

PAGE = rsc(
  '{"id":"11111111-1111-1111-1111-111111111111","slug":"opus-medium","name":"Claude Opus 5.5 (Medium Effort)",'
  '"release":{"slug":"opus","name":"Claude Opus 5.5"},"deprecated":false,"intelligenceIndex":51.2,'
  '"intelligenceIndexEvaluations":[{"slug":"omniscience","score":40.3},{"slug":"scicode","score":0.5926}],'
  '"timescaleData":{"medianOutputSpeed":74.0}},'
  '{"id":"22222222-2222-2222-2222-222222222222","slug":"old","name":"Old (max)",'
  '"release":{"slug":"old","name":"Old"},"deprecated":true,"intelligenceIndex":30.5}'
)
parsed = aaweb.parse_models(PAGE)
check("both records are read", ["old", "opus-medium"], sorted(parsed))
check("intelligence is read", 51.2, parsed["opus-medium"]["intelligence"])
check("speed comes from the timescale data", 74.0, parsed["opus-medium"]["tokensPerSecond"])
check("SciCode comes from the evaluation list, as a share", 0.5926, parsed["opus-medium"]["scicode"])
check("a model without it has None", None, parsed["old"]["scicode"])
check("the release is recorded", "opus", parsed["opus-medium"]["releaseSlug"])
check("deprecation is read", True, parsed["old"]["deprecated"])
check("a missing speed is None", None, parsed["old"]["tokensPerSecond"])
check("a page with no payload has no models", {}, aaweb.parse_models("<html></html>"))


# --------------------------------------------------------------- scicode.py

section("scicode: the official harness, reproduced")
PROBLEM = {
  "problem_id": "9",
  "required_dependencies": "import numpy as np",
  "sub_steps": [
    {"step_number": "9.1", "step_description_prompt": "Add.", "step_background": "Background: sums.",
     "function_header": "def add(a, b):\n    \"\"\"Add.\"\"\"", "return_line": "    return c",
     "test_cases": ["assert np.allclose(add(1, 2), target)", "assert np.allclose(add(2, 2), target)"]},
    {"step_number": "9.2", "step_description_prompt": "Double.", "step_background": "Background: twice.",
     "function_header": "def double(a):", "return_line": "    return d",
     "test_cases": ["assert double(2) == target"]},
  ],
}
prompt, prefix = scicode.build_prompt(PROBLEM, 2, ["def add(a, b):\n    return a + b"])
check("the background template is AA's", True, prompt.startswith(
  "PROBLEM DESCRIPTION:\nYou will be provided with problem steps along with background knowledge"))
check("earlier steps carry their background", True, "Add.\nBackground: sums." in prompt)
check("and the model's own code for them", True, "def add(a, b):\n    return a + b" in prompt)
check("the next step carries header and return line", True, "def double(a):\n\n    return d" in prompt)
check("the dependencies are listed", True, "DEPENDENCIES:" in prompt and "import numpy as np" in prompt)
check("no separator trails the last earlier step", False, "------\n\nNEXT STEP" in prompt)
check("the step file starts with the dependencies and earlier code", "import numpy as np\ndef add(a, b):\n    return a + b\n", prefix)
first, first_prefix = scicode.build_prompt(PROBLEM, 1, [])
check("step one has no earlier steps", True, "PROBLEM STEPS AND FUNCTION CODE:" in first and "------" not in first)

check("code is taken from the python block", "\ndef f():\n    return 1\n",
      scicode.extract_python_script("Here:\n```python\nimport os\ndef f():\n    return 1\n```\nDone."))
check("a bare fence works too", "\nx = 1\n", scicode.extract_python_script("```\nx = 1\n```"))
check("no fence keeps the whole reply", "y = 2", scicode.extract_python_script("y = 2"))
check("imports are dropped, as the harness does", False,
      "import" in scicode.extract_python_script("```python\nfrom math import pi\nimport numpy as np\nz = pi\n```"))
check("a named function is cut out of a file", "def b():\n    return 2",
      scicode.get_function_from_code("def a():\n    return 1\ndef b():\n    return 2", "b"))
check("unparsable code comes back whole", "def (:", scicode.get_function_from_code("def (:", "b"))
check("the function name is read from a header", "add", scicode.extract_function_name("def add(a, b):"))
check("so is a class name", "Maxwell", scicode.extract_function_name("class Maxwell(object):"))

script = scicode.test_script(PROBLEM, 1, "CODE")
check("the test script loads the step's targets", True,
      "targets = process_hdf5_to_tuple('9.1', 2)" in script)
check("each case gets its own target", True,
      script.index("target = targets[0]") < script.index("add(1, 2)") < script.index("target = targets[1]"))

section("scicode: what is scored")
real = [{"problem_id": pid, "sub_steps": [{}] * n} for pid, n in (("13", 6), ("62", 3), ("76", 4), ("1", 2))]
check("the three given steps are not scored", 6 + 3 + 4 + 2 - 3, scicode.scored_step_count(real))
check("the test split scores 288 steps", 288, scicode.SCORED_STEPS)
check("each given step's code ships with the plugin", True,
      all((scicode.SUPPORT_DIR / "steps" / f"{pid}.{n}.txt").exists() for pid, n in scicode.GIVEN_STEPS))
shim = (scicode.SUPPORT_DIR / "sitecustomize.py").read_text()
check("the sandbox puts back scipy's simps, which two problems import", True, '"simps": _simps' in shim)
check("and numpy's trapz", True, '"trapz": _np.trapezoid' in shim)
check("the vendored helpers read the targets path from the environment", True,
      'os.environ.get("SCICODE_H5"' in (scicode.SUPPORT_DIR / "scicode" / "parse" / "parse.py").read_text())
result = eval_mod.score({"a": {"status": "pass"}, "b": {"status": "fail"}, "c": {"status": "timeout"},
                         "d": {"status": "skipped"}})
check("a timeout counts as a failure", 1 / 3, result["score"])
check("a skipped step is left out", 3, result["attempted"])
check("and reported", 1, result["skipped"])


# ------------------------------------------------------------- dashboard.py

section("dashboard: labels for a column chart")
check("AA's config parenthetical is trimmed", "Claude Opus 5.5",
      dashboard.short_label("Claude Opus 5.5 (Adaptive Reasoning, Max Effort, Default Fallback)"))
check("a short parenthetical goes too", "GPT-6 Astra", dashboard.short_label("GPT-6 Astra (max)"))
check("a name with no parenthetical is untouched", "Celeris-1", dashboard.short_label("Celeris-1"))
check("only the first parenthetical is cut", "Gemini 2.5 Flash-Lite",
      dashboard.short_label("Gemini 2.5 Flash-Lite (Reasoning) (v2)"))
check("an unterminated parenthetical is still trimmed", "Weird", dashboard.short_label("Weird (unclosed"))
check("a leading space is not mistaken for one", " Weird", dashboard.short_label(" Weird (x)"))
check("an empty name is empty", "", dashboard.short_label(""))

section("dashboard: axis domains")
flat = dashboard.build_domain([10.0, 20.0, 30.0])
check("a positive-only domain still includes zero", 0.0, flat["min"])
check("and finds its max", 30.0, flat["max"])
check("zero sits at the left edge", 0.0, flat["zero"])

diverging = dashboard.build_domain([-40.0, 60.0])
check("a diverging domain keeps its min", -40.0, diverging["min"])
check("and its max", 60.0, diverging["max"])
check("zero sits 40% along", 0.4, round(diverging["zero"], 4))

check("an empty block is not a divide by zero", {"min": 0.0, "max": 0.0, "zero": 0.0}, dashboard.build_domain([]))

section("dashboard: snapshot assembly")


def build_with(free_models, catalogue, results=(), speed_rows=()):
  """Snapshot assembly with the network fetchers replaced. `catalogue` is a
  list of aaweb-shaped records."""
  original_fetch, original_aa, original_history, original_speed = (
    opencode.fetch_go_models, dashboard.aaweb.fetch_models,
    store.read_scicode_history, dashboard.store.read_data,
  )
  try:
    opencode.fetch_go_models = lambda: free_models
    dashboard.aaweb.fetch_models = lambda force=False: {
      "models": {model["slug"]: model for model in catalogue}, "fetchedAt": 1.0, "warning": None}
    store.read_scicode_history = lambda: list(results)
    dashboard.store.read_data = lambda name: ({"probedAt": "2026-01-01T00:00:00Z", "rows": list(speed_rows)}
                                               if name == "speed" else None)
    return dashboard.build_snapshot(force=True)
  finally:
    opencode.fetch_go_models, dashboard.aaweb.fetch_models = original_fetch, original_aa
    store.read_scicode_history, dashboard.store.read_data = original_history, original_speed


FREE = [{"id": "space-bunny-free", "label": "Space Bunny Free", "suffixed": True, "note": "zero-retention"},
        {"id": "longcat-2.5-preview-free", "label": "Longcat 2.5 Preview Free", "suffixed": True, "note": "zero-retention"}]

ORCHESTRATORS = [
  record("claude-opus-5-5-medium", "Claude Opus 5.5 (Adaptive Reasoning, Medium Effort)", "claude-opus-5-5", 51.2, speed=74.0, sci=0.593),
  record("claude-sonnet-5-5-medium", "Claude Sonnet 5.5 (Adaptive Reasoning, Medium Effort)", "claude-sonnet-5-5", 40.7, speed=91.4, sci=0.40),
  record("gpt-6-1-sol-medium", "GPT-6.1 Sol (medium)", "gpt-6-1-sol", 47.8, speed=60.7, sci=0.55),
  record("gpt-6-astra-medium", "GPT-6 Astra (medium)", "gpt-6-astra", 49.6, speed=46.3, sci=0.542),
]
TOPS = [
  record("claude-opus-5-5", "Claude Opus 5.5 (Adaptive Reasoning, Max Effort)", "claude-opus-5-5", 57.6, speed=92.0, sci=0.61),
  record("fable", "Claude Fable 5.1 (max)", "fable", 53.4, speed=69.0, sci=0.58),
]

bare = build_with(FREE, [])
check("the smarts chart is SciCode alone", ["scicode"], [b["scale"] for b in bare["rows"]["intelligence"]])
check("with no AA data it is empty", [0], [len(b["rows"]) for b in bare["rows"]["intelligence"]])
check("both free models are unmatched", 2, len(bare["unmatched"]))
check("there are no summary lines any more", False, "summary" in bare)

full = build_with(
  FREE, ORCHESTRATORS + TOPS,
  results=[{"opencodeId": "space-bunny-free", "score": 0.3125, "passed": 90, "attempted": 288, "skipped": 0},
           {"opencodeId": "longcat-2.5-preview-free", "score": 0.05, "passed": 14, "attempted": 280, "skipped": 8}],
  speed_rows=[{"opencodeId": "space-bunny-free", "tokensPerSecond": 162, "tokens": 1000}],
)
sci_block = full["rows"]["intelligence"][0]
sci_roles = {row["key"]: row["role"] for row in sci_block["rows"]}
check("the orchestrators are on the SciCode chart", 4, list(sci_roles.values()).count("orchestrator"))
check("so are both free models", 2, list(sci_roles.values()).count("free"))
check("AA's top model is context", "context", sci_roles.get("aa:fable"))
check("an orchestrator's own max entry is not repeated", False, "aa:claude-opus-5-5" in sci_roles)
check("AA's share is shown as a percentage", 59.3,
      [r["value"] for r in sci_block["rows"] if r["key"] == "aa:claude-opus-5-5-medium"][0])
free_sci = {r["opencodeId"]: r for r in sci_block["rows"] if r["role"] == "free"}
check("our score is a percentage too", 31.2, free_sci["space-bunny-free"]["value"])
check("a self-measured row is marked self", "self", free_sci["space-bunny-free"]["source"])
check("the note carries the pass count", True, "90/288 sub-problems" in free_sci["space-bunny-free"]["note"])
check("and any steps left out", True, "8 unanswered" in free_sci["longcat-2.5-preview-free"]["note"])
effort_full = build_with(FREE, ORCHESTRATORS, results=[{"opencodeId": "space-bunny-free", "score": 0.3,
                                                        "passed": 86, "attempted": 288, "effort": "medium"}])
check("a free model's row shows the effort it ran at", "medium",
      [r for r in effort_full["rows"]["intelligence"][0]["rows"] if r.get("opencodeId") == "space-bunny-free"][0]["configLabel"])
check("the orchestrator's effort shows as its config", "medium",
      [r for r in sci_block["rows"] if r["key"] == "aa:claude-opus-5-5-medium"][0]["configLabel"])
check("rows are sorted descending", True,
      all(a["value"] >= b["value"] for a, b in zip(sci_block["rows"], sci_block["rows"][1:])))

speed_rows_out = full["rows"]["speed"][0]["rows"]
check("the probed free model leads the speed chart", "Space Bunny Free", speed_rows_out[0]["label"])
check("and is marked self-measured", "self", speed_rows_out[0]["source"])
check("the orchestrators' speeds are there", 4, sum(1 for r in speed_rows_out if r["role"] == "orchestrator"))

warned = build_with(FREE, TOPS)
check("a missing orchestrator is called out", True,
      any("no entry for" in w and "gpt-6-astra-medium" in w for w in warned["warnings"]))


section("dashboard: which operations still owe us a result")
# The buttons in the window's Benchmark box are ringed red while any free model
# has no result from the operation behind that button. Coverage is per model, not
# per timestamp: measuring one of two free models has still not measured the other.

never = build_with(FREE, [])
check("with nothing run, every free model owes a SciCode score",
      ["space-bunny-free", "longcat-2.5-preview-free"], never["pending"]["intelligence"])
check("and a speed measurement", ["space-bunny-free", "longcat-2.5-preview-free"], never["pending"]["speed"])
check("AA is never flagged, because we never run it", False, "aa" in never["pending"])

half = build_with(
  FREE, [],
  results=[{"opencodeId": "space-bunny-free", "score": 0.3, "passed": 86, "attempted": 288}],
  speed_rows=[{"opencodeId": "space-bunny-free", "tokensPerSecond": 475, "tokens": 561}],
)
check("one model benchmarked leaves only the other pending",
      ["longcat-2.5-preview-free"], half["pending"]["intelligence"])
check("one model probed leaves only the other pending",
      ["longcat-2.5-preview-free"], half["pending"]["speed"])

done = build_with(
  FREE, [],
  results=[{"opencodeId": model["id"], "score": 0.3, "passed": 86, "attempted": 288} for model in FREE],
  speed_rows=[{"opencodeId": model["id"], "tokensPerSecond": 400, "tokens": 500} for model in FREE],
)
check("once every model has a score nothing is pending", [], done["pending"]["intelligence"])
check("and likewise for speed", [], done["pending"]["speed"])

check("with no free models nothing is pending", {"intelligence": [], "speed": []},
      build_with([], [])["pending"])


# ------------------------------------------------------------------ eval.py

section("eval: run state survives the process that wrote it")
idle = eval_mod.read_state()
check("an absent state file reads as idle", False, idle["running"])

eval_mod.write_state({**eval_mod.IDLE_STATE, "running": True, "runId": "run-1", "pid": 999999})
stale = eval_mod.read_state()
check("a dead pid does not read as running", False, stale["running"])
check("and says why", True, "interrupted" in (stale["message"] or "").lower())

eval_mod.write_state({**eval_mod.IDLE_STATE, "running": True, "runId": "run-1", "pid": 1})
check("a live pid does read as running", True, eval_mod.read_state()["running"])

eval_mod.write_state({**eval_mod.IDLE_STATE, "running": False, "progress": 0.5, "currentQuestion": 600,
                      "totalQuestions": 1200, "message": "Run complete"})
finished = eval_mod.read_state()
check("a finished run keeps its totals", 1200, finished["totalQuestions"])
check("and its global question count", 600, finished["currentQuestion"])

check("state was written atomically into the sandbox", True,
      (Path(SANDBOX.name) / "eval-state.json").exists())
# A live run can legitimately update the real file meanwhile, so a change only
# counts against the tests when no run is in progress.
_real_state_after = _real_state.stat().st_mtime_ns if _real_state.exists() else None
_live_run = _real_state.exists() and '"running": true' in _real_state.read_text()
check("and not into the real data directory", True,
      _real_state_after == _real_state_before or _live_run)

section("eval: a run counts progress across every model")
TWO_PROBLEMS = [
  {"problem_id": "1", "required_dependencies": "", "sub_steps": [
    {"step_number": f"1.{n}", "step_description_prompt": f"P1 step {n}", "step_background": "",
     "function_header": f"def f{n}():", "return_line": "", "test_cases": []} for n in (1, 2, 3)]},
  {"problem_id": "2", "required_dependencies": "", "sub_steps": [
    {"step_number": f"2.{n}", "step_description_prompt": f"P2 step {n}", "step_background": "",
     "function_header": f"def g{n}():", "return_line": "", "test_cases": []} for n in (1, 2)]},
]


def run_patched(complete_fn, test_fn=lambda script: "pass", models=None):
  patches = {
    (store, "opencode_key"): lambda: ("key", "test"),
    (eval_mod.opencode, "fetch_go_models"): lambda: [{"id": "a-free", "label": "A Free"}, {"id": "b-free", "label": "B Free"}],
    (eval_mod.scicode, "ensure_env"): lambda say: None,
    (eval_mod.scicode, "ensure_data"): lambda say: None,
    (eval_mod.scicode, "fetch_problems"): lambda split="test": TWO_PROBLEMS,
    (eval_mod.scicode, "run_test"): test_fn,
    (eval_mod.complete_mod, "complete"): complete_fn,
    (eval_mod.time, "sleep"): lambda seconds: None,
  }
  saved = {target: getattr(*target) for target in patches}
  try:
    for (owner, name), value in patches.items():
      setattr(owner, name, value)
    return eval_mod.run(models)
  finally:
    for (owner, name), value in saved.items():
      setattr(owner, name, value)


history_before = len(store.read_scicode_history())
writes = []
original_write = eval_mod.write_state
try:
  eval_mod.write_state = lambda state: (writes.append(state.get("currentQuestion")), original_write(state))
  final = run_patched(lambda key, model, prompt, tokens, timeout=0, effort=None: "```python\ndef f():\n    pass\n```")
finally:
  eval_mod.write_state = original_write
counts = [c for c in writes if isinstance(c, int)]
check("the run finishes", "Run complete", final["message"])
check("it counts every step of every model", 10, final["totalQuestions"])
check("the counter moved during the run", True, {1, 2, 3, 4, 5, 6, 7, 8, 9} <= set(counts))
check("and never went backwards", True, counts == sorted(counts))
check("one history entry per free model", history_before + 2, len(store.read_scicode_history()))
check("all steps passing scores 1", 1.0, store.read_scicode_history()[0]["score"])
check("the run asks for medium effort, like the workers", "medium", store.read_scicode_history()[0]["effort"])
check("a finished model leaves no progress file behind", False,
      store.data_path("scicode-progress-a-free").exists())

section("eval: each step sees the model's own earlier code")
seen = []
def remembering(key, model, prompt, tokens, timeout=0, effort=None):
  seen.append(prompt)
  step = re.search(r"NEXT STEP.*?(P\d step \d)", prompt, re.S).group(1)
  return f"```python\ndef answer():\n    return '{step}'\n```"
run_patched(remembering, models=["a-free"])
third = [p for p in seen if re.search(r"NEXT STEP.*?P1 step 3", p, re.S)][0]
check("step 3 is shown the answers to steps 1 and 2", True,
      "return 'P1 step 1'" in third and "return 'P1 step 2'" in third)

section("eval: a request that keeps failing skips the rest of its problem")
def failing(key, model, prompt, tokens, timeout=0, effort=None):
  if re.search(r"NEXT STEP.*?P1 step 2", prompt, re.S):
    raise RuntimeError(f"{model} request failed: timed out")
  return "```python\nx = 1\n```"
before = len(store.read_scicode_history())
final = run_patched(failing, test_fn=lambda script: "fail", models=["b-free"])
history = store.read_scicode_history()
check("the run still completes", "Run complete", final["message"])
check("only the named model was benchmarked", before + 1, len(history))
check("and it was that model", "b-free", history[0]["opencodeId"])
check("the failed step and the one after it are skipped", 2, history[0]["skipped"])
check("so three steps were scored", 3, history[0]["attempted"])

section("eval: an interrupted run resumes")
store.write_data("scicode-progress-a-free", {"dataset": scicode.DATASET_REVISION, "steps": {
  "1.1": {"status": "pass", "code": "def f1():\n    return 'kept'"},
  "1.2": {"status": "fail", "code": "def f2():\n    return 'kept too'"}}})
asked = []
def counting(key, model, prompt, tokens, timeout=0, effort=None):
  asked.append(prompt)
  return "```python\ny = 2\n```"
run_patched(counting, models=["a-free"])
check("finished steps are not asked again", 3, len(asked))
check("and the next step builds on the saved code", True,
      any("return 'kept too'" in p for p in asked))
check("their results count", 1 + 3, store.read_scicode_history()[0]["passed"])
store.write_data("scicode-progress-a-free", {"dataset": "an-older-revision", "steps": {"1.1": {"status": "pass", "code": ""}}})
check("progress from another dataset revision is ignored", {}, eval_mod._load_progress("a-free"))
store.data_path("scicode-progress-a-free").unlink()

try:
  eval_mod._chosen([{"id": "a-free", "label": "A"}], ["nope-free"])
  check("naming an unknown model is an error", True, False)
except RuntimeError as error:
  check("naming an unknown model is an error", True, "nope-free" in str(error))

section("speed: probing one model keeps the others")
store.write_data("speed", {"probedAt": "t0", "rows": [
  {"opencodeId": "a-free", "tokensPerSecond": 475, "tokens": 561},
  {"opencodeId": "b-free", "tokensPerSecond": 81, "tokens": 700}]})
speed.save_rows([{"opencodeId": "b-free", "tokensPerSecond": 90, "tokens": 650}])
kept = {row["opencodeId"]: row["tokensPerSecond"] for row in store.read_data("speed")["rows"]}
check("the other model's measurement survives", 475, kept["a-free"])
check("the probed model is updated", 90, kept["b-free"])
speed.save_rows([{"opencodeId": "a-free", "tokensPerSecond": None, "error": "buffered"}])
check("a failed sample doesn't erase a good one", 475,
      {row["opencodeId"]: row["tokensPerSecond"] for row in store.read_data("speed")["rows"]}["a-free"])
speed.save_rows([{"opencodeId": "c-free", "tokensPerSecond": None, "error": "buffered"}])
check("but a model never measured records its failure", "buffered",
      {row["opencodeId"]: row.get("error") for row in store.read_data("speed")["rows"]}["c-free"])

section("speed: reasoning tokens are timed from the first token")
# A reasoning model streams its thinking first. The token count includes it, so
# the window has to as well: timing only the visible answer reported Space
# Bunny at 621 tok/s.
class _Stream:
  def __init__(self, lines):
    self.data = "".join(f"data: {json.dumps(line)}\n\n" for line in lines).encode() + b"data: [DONE]\n\n"
    self.chunks = [self.data[i:i + 40] for i in range(0, len(self.data), 40)] + [b""]
  def read(self, size):
    return self.chunks.pop(0)
  def __enter__(self):
    return self
  def __exit__(self, *exc):
    return False

EVENTS = ([{"choices": [{"delta": {"reasoning_content": "hmm"}}]}] * 4
          + [{"choices": [{"delta": {"content": "1\n2\n"}}]}] * 2
          + [{"choices": [], "usage": {"completion_tokens": 600}}])
clock = iter(float(t) for t in range(100))
original_urlopen, original_clock = speed.urllib.request.urlopen, speed.time.perf_counter
try:
  speed.urllib.request.urlopen = lambda request, timeout=0: _Stream(EVENTS)
  speed.time.perf_counter = lambda: next(clock)
  sample = speed.sample_once("key", "space-bunny-free", 0)
finally:
  speed.urllib.request.urlopen, speed.time.perf_counter = original_urlopen, original_clock
check("the window starts at the first reasoning token", 5.0, sample["windowSeconds"])
check("so 600 tokens over it are 120 tok/s, not 600", 120.0, sample["tps"])
check("three samples per model", 3, speed.SAMPLES)


print()
print(f"{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
