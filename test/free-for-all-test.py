#!/usr/bin/python3
"""Pins the free-for-all logic ported out of the Paseo plugin.

Three things here are easy to get subtly wrong and expensive to get wrong:

  * the fuzzy join, because a wrong match publishes a fabricated benchmark
    number as though it were real;
  * the grading arithmetic, because the Omniscience index is calibration rather
    than accuracy and a sign error inverts the whole chart;
  * the eval's progress readout, which was wrong in the original and is easy to
    regress.

No network. The fetchers are replaced with fixtures, so the suite passes on a
machine with no keys and no subscription.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from ffa import aaweb, complete, dashboard, eval as eval_mod, match, omniscience, opencode, speed, store  # noqa: E402

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
def record(slug, name, release, intelligence, deprecated=False, speed=None, omni=None):
  return {"slug": slug, "name": name, "releaseSlug": release, "intelligence": intelligence,
          "tokensPerSecond": speed, "omniscience": omni, "deprecated": deprecated}

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
  '"omniscience":null,"intelligenceIndexEvaluations":[{"slug":"omniscience","score":40.3}],'
  '"timescaleData":{"medianOutputSpeed":74.0}},'
  '{"id":"22222222-2222-2222-2222-222222222222","slug":"old","name":"Old (max)",'
  '"release":{"slug":"old","name":"Old"},"deprecated":true,"intelligenceIndex":30.5,"omniscience":-13.1}'
)
parsed = aaweb.parse_models(PAGE)
check("both records are read", ["old", "opus-medium"], sorted(parsed))
check("intelligence is read", 51.2, parsed["opus-medium"]["intelligence"])
check("speed comes from the timescale data", 74.0, parsed["opus-medium"]["tokensPerSecond"])
check("omniscience prefers the evaluation list", 40.3, parsed["opus-medium"]["omniscience"])
check("and falls back to the top-level field", -13.1, parsed["old"]["omniscience"])
check("the release is recorded", "opus", parsed["opus-medium"]["releaseSlug"])
check("deprecation is read", True, parsed["old"]["deprecated"])
check("a missing speed is None", None, parsed["old"]["tokensPerSecond"])
check("a page with no payload has no models", {}, aaweb.parse_models("<html></html>"))


# ----------------------------------------------------------- omniscience.py

section("omniscience: grading")
check("a bare letter grades itself", "A", omniscience.parse_grade("A"))
check("a verbose verdict is read", "B", omniscience.parse_grade("B: INCORRECT"))
check("surrounding chatter is ignored", "C", omniscience.parse_grade("I think the answer is C"))
check("lowercase is accepted", "D", omniscience.parse_grade("d"))
check("a malformed reply scores as not attempted", "D", omniscience.parse_grade("no idea, sorry"))
check("an empty reply scores as not attempted", "D", omniscience.parse_grade(""))
check("ABCD is not a grade", "D", omniscience.parse_grade("ABCD"))

section("omniscience: the index is calibration, not accuracy")
all_correct = omniscience.score_grades(["A"] * 100)
check("all correct is +1", 1.0, all_correct["index"])
check("all correct is 100% accurate", 1.0, all_correct["accuracy"])
check("all correct answered everything", 100, all_correct["answered"])

all_wrong = omniscience.score_grades(["B"] * 100)
check("all wrong is -1", -1.0, all_wrong["index"])
check("all wrong is 0% accurate", 0.0, all_wrong["accuracy"])
check("all wrong is 100% hallucination", 1.0, all_wrong["hallucinationRate"])

all_refused = omniscience.score_grades(["D"] * 100)
check("all refused is 0, not -1", 0.0, all_refused["index"])
check("all refused answered nothing", 0, all_refused["answered"])
check("but still counts as hallucination", 1.0, all_refused["hallucinationRate"])

mixed = omniscience.score_grades(["A", "B", "C", "D"])
check("partial answers score the same as wrong", -0.25, mixed["index"])
check("mixed accuracy", 0.25, mixed["accuracy"])
check("mixed hallucination is 1 - accuracy", 0.75, mixed["hallucinationRate"])
check("empty input is not a crash", 0, omniscience.score_grades([])["total"])

section("omniscience: prompts")
item = {"domain": "Finance", "topic": "Accounting", "question": "Q?", "answer": "A"}
answer = omniscience.answer_prompt(item)
check("the answer prompt names the domain", True, "Finance" in answer)
check("and the topic", True, "Accounting" in answer)
check("and invites refusal", True, "better that you say this" in answer)
check("and carries the question", True, answer.endswith("Q?"))

grader = omniscience.grader_prompt(item, "my prediction")
check("the grader gets the question", True, "\nQuestion: Q?\n" in grader)
check("the grader gets the gold target", True, "Gold target: A\n" in grader)
check("the grader gets the prediction", True, "Predicted answer: my prediction" in grader)
check("no placeholder survives", False, "{question}" in grader or "{criterion}" in grader or "{answer}" in grader)
check("the rubric is intact", True, "NOT_ATTEMPTED" in grader and "PARTIAL_ANSWER" in grader)
check("all seven examples are present", 7, grader.count("Example "))
check("the rubric is the lighteval one", True, "last significant figure" in grader)
injected = omniscience.grader_prompt(
  {"domain": "D", "topic": "T", "question": "What is {criterion}?", "answer": "GOLD"}, "PRED")
check("a question containing a placeholder is left alone", True, "What is {criterion}?" in injected)
check("and the gold target did not leak into it", False, "What is GOLD?" in injected)
check("the real gold target still went in", True, "Gold target: GOLD\n" in injected)

section("omniscience: the rubric was copied byte for byte")
check("every example survived the port", 7, omniscience.GRADER_PREAMBLE.count("Example "))
check("the sign-off survived", True,
      omniscience.GRADER_PREAMBLE.rstrip().endswith('Just return the letters "A", "B", "C", or "D", with no text around it.'))
check("the typo in example 4 is preserved", True, "barn-façade" in omniscience.GRADER_PREAMBLE)
check("the awkward case is preserved", True,
      "A pretrainer's guide to training data" in omniscience.GRADER_PREAMBLE)


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


def build_with(free_models, catalogue, grades=(), speed_rows=()):
  """Snapshot assembly with the network fetchers replaced. `catalogue` is a
  list of aaweb-shaped records."""
  original_fetch, original_aa, original_history, original_speed = (
    opencode.fetch_go_models, dashboard.aaweb.fetch_models,
    store.read_eval_history, dashboard.store.read_data,
  )
  try:
    opencode.fetch_go_models = lambda: free_models
    dashboard.aaweb.fetch_models = lambda force=False: {
      "models": {model["slug"]: model for model in catalogue}, "fetchedAt": 1.0, "warning": None}
    store.read_eval_history = lambda: list(grades)
    dashboard.store.read_data = lambda name: ({"probedAt": "2026-01-01T00:00:00Z", "rows": list(speed_rows)}
                                               if name == "speed" else None)
    return dashboard.build_snapshot(force=True)
  finally:
    opencode.fetch_go_models, dashboard.aaweb.fetch_models = original_fetch, original_aa
    store.read_eval_history, dashboard.store.read_data = original_history, original_speed


FREE = [{"id": "space-bunny-free", "label": "Space Bunny Free", "suffixed": True, "note": "zero-retention"},
        {"id": "longcat-2.5-preview-free", "label": "Longcat 2.5 Preview Free", "suffixed": True, "note": "zero-retention"}]

ORCHESTRATORS = [
  record("claude-opus-5-5-medium", "Claude Opus 5.5 (Adaptive Reasoning, Medium Effort)", "claude-opus-5-5", 51.2, speed=74.0, omni=40.3),
  record("claude-sonnet-5-5-medium", "Claude Sonnet 5.5 (Adaptive Reasoning, Medium Effort)", "claude-sonnet-5-5", 40.7, speed=91.4, omni=20.1),
  record("gpt-6-1-sol-medium", "GPT-6.1 Sol (medium)", "gpt-6-1-sol", 47.8, speed=60.7, omni=40.0),
  record("gpt-6-astra-medium", "GPT-6 Astra (medium)", "gpt-6-astra", 49.6, speed=46.3, omni=42.2),
]
TOPS = [
  record("claude-opus-5-5", "Claude Opus 5.5 (Adaptive Reasoning, Max Effort)", "claude-opus-5-5", 57.6, speed=92.0, omni=46.4),
  record("fable", "Claude Fable 5.1 (max)", "fable", 53.4, speed=69.0, omni=43.5),
]

bare = build_with(FREE, [])
check("the smarts blocks are Omniscience then AA's index", ["omniscience", "aa-index"],
      [b["scale"] for b in bare["rows"]["intelligence"]])
check("with no AA data they are empty", [0, 0], [len(b["rows"]) for b in bare["rows"]["intelligence"]])
check("both free models are unmatched", 2, len(bare["unmatched"]))
check("and there is nothing to summarise", [], bare["summary"])

full = build_with(
  FREE, ORCHESTRATORS + TOPS,
  grades=[{"opencodeId": "space-bunny-free", "index": 0.12, "accuracy": 0.41,
           "hallucinationRate": 0.59, "answered": 80, "total": 100},
          {"opencodeId": "longcat-2.5-preview-free", "index": -0.05, "accuracy": 0.3,
           "hallucinationRate": 0.7, "answered": 70, "total": 100}],
  speed_rows=[{"opencodeId": "space-bunny-free", "tokensPerSecond": 475, "tokens": 561}],
)
blocks = {block["scale"]: block for block in full["rows"]["intelligence"]}
omni_roles = {row["key"]: row["role"] for row in blocks["omniscience"]["rows"]}
check("the orchestrators are on the Omniscience chart", 4, list(omni_roles.values()).count("orchestrator"))
check("so are both free models", 2, list(omni_roles.values()).count("free"))
check("AA's top model is context", "context", omni_roles.get("aa:fable"))
check("an orchestrator's own max entry is not repeated", False, "aa:claude-opus-5-5" in omni_roles)
free_omni = [row for row in blocks["omniscience"]["rows"] if row["role"] == "free"]
check("our index is expressed in points", 12.0, [r["value"] for r in free_omni if r["opencodeId"] == "space-bunny-free"][0])
check("a self-measured row is marked self", "self", free_omni[0]["source"])
check("the note carries the question count", True, "100 questions" in free_omni[0]["note"])
check("the orchestrator's effort shows as its config", "medium",
      [r for r in blocks["aa-index"]["rows"] if r["key"] == "aa:claude-opus-5-5-medium"][0]["configLabel"])
check("rows are sorted descending", True,
      all(a["value"] >= b["value"] for a, b in zip(blocks["omniscience"]["rows"], blocks["omniscience"]["rows"][1:])))
check("a negative score keeps its sign", -5.0,
      [r["value"] for r in free_omni if r["opencodeId"] == "longcat-2.5-preview-free"][0])
check("so the domain goes below zero", True, blocks["omniscience"]["domain"]["min"] < 0)

speed_rows_out = full["rows"]["speed"][0]["rows"]
check("the probed free model leads the speed chart", "Space Bunny Free", speed_rows_out[0]["label"])
check("and is marked self-measured", "self", speed_rows_out[0]["source"])
check("the orchestrators' speeds are there", 4, sum(1 for r in speed_rows_out if r["role"] == "orchestrator"))

check("the summary compares a free model to the orchestrators", True,
      any(line.startswith("Space Bunny Free: Omniscience 12 vs your orchestrators' 20–42") for line in full["summary"]))
check("and states its speed against theirs", True, any("× their typical speed" in line for line in full["summary"]))
check("and names the smarter free model", "Smarter free model right now: Space Bunny Free", full["summary"][-1])

warned = build_with(FREE, TOPS)
check("a missing orchestrator is called out", True,
      any("no entry for" in w and "gpt-6-astra-medium" in w for w in warned["warnings"]))


section("dashboard: which operations still owe us a result")
# The buttons in the window's Benchmark box are ringed red while any free model
# has no result from the operation behind that button. Coverage is per model, not
# per timestamp: measuring one of two free models has still not measured the other.

never = build_with(FREE, [])
check("with nothing run, every free model owes an intelligence score",
      ["space-bunny-free", "longcat-2.5-preview-free"], never["pending"]["intelligence"])
check("and a speed measurement", ["space-bunny-free", "longcat-2.5-preview-free"], never["pending"]["speed"])
check("AA is never flagged, because we never run it", False, "aa" in never["pending"])

half = build_with(
  FREE, [],
  grades=[{"opencodeId": "space-bunny-free", "index": 0.1, "accuracy": 0.5,
           "hallucinationRate": 0.5, "answered": 300, "total": 600}],
  speed_rows=[{"opencodeId": "space-bunny-free", "tokensPerSecond": 475, "tokens": 561}],
)
check("one model graded leaves only the other pending",
      ["longcat-2.5-preview-free"], half["pending"]["intelligence"])
check("one model probed leaves only the other pending",
      ["longcat-2.5-preview-free"], half["pending"]["speed"])

done = build_with(
  FREE, [],
  grades=[{"opencodeId": model["id"], "index": 0.1, "accuracy": 0.5,
           "hallucinationRate": 0.5, "answered": 300, "total": 600} for model in FREE],
  speed_rows=[{"opencodeId": model["id"], "tokensPerSecond": 400, "tokens": 500} for model in FREE],
)
check("once every model has a grade nothing is pending", [], done["pending"]["intelligence"])
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
# The counter used to be defined and never called, so a run sat at 0% until it
# finished. Run the real loop with the network replaced.
patches = {
  (store, "opencode_key"): lambda: ("key", "test"),
  (eval_mod.opencode, "fetch_go_models"): lambda: [{"id": "a-free", "label": "A Free"}, {"id": "b-free", "label": "B Free"}],
  (eval_mod.omniscience, "fetch_questions"): lambda: [
    {"questionId": n, "domain": "D", "topic": "T", "question": f"Q{n}", "answer": "A"} for n in range(12)],
  (eval_mod.complete_mod, "complete"): lambda key, model, prompt, tokens: "an answer",
  (eval_mod, "grade"): lambda prompt: "A",
}
saved = {target: getattr(*target) for target in patches}
history_before = len(store.read_eval_history())
writes = []
original_write = eval_mod.write_state
try:
  for (owner, name), value in patches.items():
    setattr(owner, name, value)
  eval_mod.write_state = lambda state: (writes.append(state.get("currentQuestion")), original_write(state))
  final = eval_mod.run(limit=3)
finally:
  for (owner, name), value in saved.items():
    setattr(owner, name, value)
  eval_mod.write_state = original_write
counts = [c for c in writes if isinstance(c, int)]
check("the run finishes", "Run complete", final["message"])
check("it graded limit x models questions", 6, final["totalQuestions"])
check("the counter moved during the run", True, {1, 2, 3, 4, 5} <= set(counts))
check("and never went backwards", True, counts == sorted(counts))
check("one history entry per free model", history_before + 2, len(store.read_eval_history()))

section("eval: a slow answer doesn't sink the run")
flaky = {"calls": 0}
def flaky_complete(key, model, prompt, tokens):
  flaky["calls"] += 1
  if "Q0" in prompt:
    raise RuntimeError(f"{model} request failed: The read operation timed out")
  if "Q1" in prompt and flaky["calls"] % 2 == 1:
    raise RuntimeError(f"{model} request failed: reset")
  return "an answer"
patches = {
  (store, "opencode_key"): lambda: ("key", "test"),
  (eval_mod.opencode, "fetch_go_models"): lambda: [{"id": "a-free", "label": "A Free"}, {"id": "b-free", "label": "B Free"}],
  (eval_mod.omniscience, "fetch_questions"): lambda: [
    {"questionId": n, "domain": "D", "topic": "T", "question": f"Q{n}", "answer": "A"} for n in range(4)],
  (eval_mod.complete_mod, "complete"): flaky_complete,
  (eval_mod, "grade"): lambda prompt: "A",
  (eval_mod.time, "sleep"): lambda seconds: None,
}
saved = {target: getattr(*target) for target in patches}
before = len(store.read_eval_history())
try:
  for (owner, name), value in patches.items():
    setattr(owner, name, value)
  final = eval_mod.run(limit=4, models=["b-free"])
finally:
  for (owner, name), value in saved.items():
    setattr(owner, name, value)
history = store.read_eval_history()
check("the run still completes", "Run complete", final["message"])
check("only the named model was graded", before + 1, len(history))
check("and it was that model", "b-free", history[0]["opencodeId"])
check("the question that never answered is skipped, not scored", 1, history[0]["skipped"])
check("so the score covers the rest", 3, history[0]["total"])
check("a question that failed once was retried and kept", 3, history[0]["answered"])
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

section("eval: sampling and grading")
questions = [{"questionId": n} for n in range(600)]
sampled = eval_mod.sample_questions(questions, 100)
check("a sample has the requested size", 100, len(sampled))
check("it strides the whole set, not its head", True, sampled[-1]["questionId"] > 500)
check("no limit means every question", 600, len(eval_mod.sample_questions(questions, None)))
check("a limit past the end is the whole set", 600, len(eval_mod.sample_questions(questions, 900)))
check("the default run is sized for Big Pickle", 100, eval_mod.DEFAULT_QUESTIONS)
check("the grader is Big Pickle on Zen", "opencode/big-pickle", eval_mod.GRADER_MODEL)

class _Done:
  def __init__(self, stdout, stderr=""):
    self.stdout, self.stderr = stdout, stderr

calls = []
original_run = eval_mod.subprocess.run
try:
  eval_mod.subprocess.run = lambda args, **kw: (calls.append((args, kw)), _Done(
    '{"type":"step_start"}\n{"type":"text","part":{"type":"text","text":"B"}}\nnot json\n'))[1]
  verdict = eval_mod.grade("the prompt")
  args, kwargs = calls[0]
  check("the verdict is the text part", "B", verdict)
  check("the grader runs read-only", True, args[args.index("--agent") + 1] == "plan")
  check("without plugins", True, "--pure" in args)
  check("with the grader model", "opencode/big-pickle", args[args.index("-m") + 1])
  check("in a scratch directory, not the plugin's", True, "ogw-grade-" in kwargs["cwd"])
  eval_mod.subprocess.run = lambda args, **kw: _Done("", "Error: daily limit reached")
  try:
    eval_mod.grade("x")
    check("no verdict is an error", True, False)
  except RuntimeError as error:
    check("no verdict is an error that says why", True, "daily limit reached" in str(error))
finally:
  eval_mod.subprocess.run = original_run


print()
print(f"{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
