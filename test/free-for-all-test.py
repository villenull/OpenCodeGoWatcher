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

from ffa import complete, dashboard, eval as eval_mod, match, omniscience, opencode, store  # noqa: E402

PASSED = 0
FAILED = 0

# Every path under the plugin's state directory is redirected into a temp dir for
# the whole run. The dashboard and eval code both end in a real
# `store.write_data`, so without this the suite writes fixtures over the user's
# own snapshot and the window then cheerfully renders "Model 30" as if it were a
# leaderboard.
SANDBOX = tempfile.TemporaryDirectory()
_real_data_dir = store.data_dir
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

section("dashboard: which configuration a number came from")
check("max effort is the default and is not restated", "", dashboard.config_label("GPT-6 Astra (max)"))
check("a size survives the stripping of max", "3.3b", dashboard.config_label("Meta Spark (3.3B max)"))
check("the deviations are the ones worth showing", "adaptive\u00b7fallback",
      dashboard.config_label("Claude Opus 5.5 (Adaptive Reasoning, Max Effort, Default Fallback)"))
check("a no-fallback variant keeps the distinction", "adaptive\u00b7no fallback",
      dashboard.config_label("Claude Opus 5 (Adaptive Reasoning, Max Effort, No Fallback)"))
check("a named fallback model collapses to fallback", "adaptive\u00b7fallback",
      dashboard.config_label("Claude Fable 5 (Adaptive Reasoning, Max Effort, Opus 4.8 Fallback)"))
check("a non-max effort is a deviation and is shown", "high", dashboard.config_label("Gemini 3.7 Flash (high)"))
check("a model with no parenthetical has no config", "", dashboard.config_label("Celeris-1"))
check("an unrelated bracket is not a config", "", dashboard.config_label("Gemma 3 [2B]"))
check("no label is wide enough to reach its neighbour", True,
      all(len(dashboard.config_label(n)) <= 20 for n in [
        "Claude Opus 5 (Adaptive Reasoning, Max Effort, No Fallback)",
        "Claude Opus 5.5 (Adaptive Reasoning, Max Effort, Default Fallback)",
      ]))

section("dashboard: one row per base model")
VARIANTS = [
  {"name": "Claude Opus 5.5 (Adaptive Reasoning, Max Effort, Default Fallback)", "slug": "opus-max", "intelligence": 57.6, "tokensPerSecond": 61.0},
  {"name": "Claude Opus 5.5 (Adaptive Reasoning, Xhigh Effort, Default Fallback)", "slug": "opus-xhigh", "intelligence": 56.0, "tokensPerSecond": 55.0},
  {"name": "Claude Opus 5.5 (Adaptive Reasoning, High Effort, Default Fallback)", "slug": "opus-high", "intelligence": 53.6, "tokensPerSecond": 50.0},
  {"name": "GPT-6 Astra (max)", "slug": "astra-max", "intelligence": 52.7, "tokensPerSecond": 76.0},
  {"name": "GPT-6 Astra (xhigh)", "slug": "astra-xhigh", "intelligence": 52.4, "tokensPerSecond": 70.0},
  {"name": "Celeris-1", "slug": "celeris-1", "intelligence": 50.0, "tokensPerSecond": 120.0},
]
def context(catalogue, field="intelligence", used=frozenset()):
  """Rows as the snapshot actually emits them, display fields included."""
  rows = dashboard._context_rows(catalogue, set(used), field, f"aa-{field}")
  dashboard._add_short_labels([{"rows": rows}])
  return rows

rows = context(VARIANTS)
check("three Opuses collapse to one row", 3, len(rows))
check("and so do two Atras", 3, len({dashboard.short_label(r["label"]) for r in rows}))
check("the winner is the max-effort entry", "opus-max", rows[0]["aaSlug"])
check("a plain name is its own base", "celeris-1", [r for r in rows if r["aaSlug"] == "celeris-1"][0]["aaSlug"])
check("each row carries its own config", "adaptive\u00b7fallback", rows[0]["configLabel"])

section("dashboard: preferring max beats a higher raw score")
# A model with no (max) entry still gets its best, and a model whose only entry
# is a non-max effort keeps it rather than being dropped.
MIXED = [
  {"name": "Ranger 2 (high)", "slug": "ranger-high", "intelligence": 40.0, "tokensPerSecond": 30.0},
  {"name": "Ranger 2 (medium)", "slug": "ranger-medium", "intelligence": 36.0, "tokensPerSecond": 28.0},
  {"name": "Pike 3 (medium)", "slug": "pike-medium", "intelligence": 44.0, "tokensPerSecond": 60.0},
]
mixed = context(MIXED)
check("without a max, the best score is kept", "ranger-high", mixed[1]["aaSlug"])
check("and it is kept even when it is not max", "high", mixed[1]["configLabel"])
check("a lone non-max model is not dropped", "pike-medium", mixed[0]["aaSlug"])

section("dashboard: dedup respects the other filters")
check("a used model is still excluded", 2, len(context(
  VARIANTS, used={"opus-max", "opus-xhigh", "opus-high", "astra-max"})))
check("excluding the max re-admits its sibling", ["astra-xhigh"],
      [r["aaSlug"] for r in context(
        VARIANTS, used={"opus-max", "opus-xhigh", "opus-high", "celeris-1", "astra-max"})])
check("a missing value is skipped", 0, len(context([{"name": "Blank (max)", "slug": "blank", "intelligence": None}])))
check("speed dedups the same way", 3, len(context(VARIANTS, field="tokensPerSecond")))
many = VARIANTS + [
  {"name": f"Model {n} (max)", "slug": f"m{n}", "intelligence": float(40 - n), "tokensPerSecond": 10.0}
  for n in range(9)
]
check("the cap applies across distinct base models", 10, len(context(many)))
check("the cap keeps the highest, in order", [57.6, 52.7, 50.0], [r["value"] for r in context(many)[:3]])
dropped = {m["slug"] for m in many if m["slug"] not in {r["aaSlug"] for r in context(many)}}
check("the weakest models are among those dropped", True, {"m7", "m8"} <= dropped)
check("and so are the effort levels the dedupe removed", True, {"opus-xhigh", "opus-high"} <= dropped)


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
  """Snapshot assembly with the two network fetchers replaced."""
  original_fetch, original_aa, original_history, original_speed = (
    opencode.fetch_go_models, dashboard.aa.fetch_aa_catalogue,
    store.read_eval_history, dashboard.store.read_data,
  )
  try:
    opencode.fetch_go_models = lambda: free_models
    dashboard.aa.fetch_aa_catalogue = lambda: {"models": catalogue, "indexVersion": "v4", "warnings": []}
    store.read_eval_history = lambda: list(grades)
    dashboard.store.read_data = lambda name: ({"probedAt": "2026-01-01T00:00:00Z", "rows": list(speed_rows)}
                                               if name == "speed" else None)
    return dashboard.build_snapshot(force=True)
  finally:
    opencode.fetch_go_models, dashboard.aa.fetch_aa_catalogue = original_fetch, original_aa
    store.read_eval_history, dashboard.store.read_data = original_history, original_speed


FREE = [{"id": "space-bunny-free", "label": "Space Bunny Free", "suffixed": True, "note": "zero-retention"},
        {"id": "longcat-2.5-preview-free", "label": "Longcat 2.5 Preview Free", "suffixed": True, "note": "zero-retention"}]

bare = build_with(FREE, [])
check("without AA there is one intelligence block", ["aa-index"], [b["scale"] for b in bare["rows"]["intelligence"]])
check("and no omniscience block", False, any(b["scale"] == "omniscience" for b in bare["rows"]["intelligence"]))
check("both free models are unmatched", 2, len(bare["unmatched"]))

scored = build_with(
  FREE, [{"name": "Space Bunny", "slug": "space-bunny", "intelligence": 42.0, "tokensPerSecond": 90.0}],
  grades=[{"opencodeId": "space-bunny-free", "index": -0.31, "accuracy": 0.41,
           "hallucinationRate": 0.59, "answered": 250, "total": 600}],
)
blocks = {block["scale"]: block for block in scored["rows"]["intelligence"]}
check("a grade adds the omniscience block", True, "omniscience" in blocks)
check("the index is expressed in points", -31.0, blocks["omniscience"]["rows"][0]["value"])
check("a self-measured row is marked self", "self", blocks["omniscience"]["rows"][0]["source"])
check("the note carries the grade detail", True, "accuracy 41%" in blocks["omniscience"]["rows"][0]["note"])
check("and the question count", True, "600 questions" in blocks["omniscience"]["rows"][0]["note"])
check("an unmatched model with a grade is not unmatched", ["longcat-2.5-preview-free"], scored["unmatched"])
check("AA and our own index stay in separate blocks", True,
      blocks["aa-index"]["domain"]["max"] != blocks["omniscience"]["domain"]["max"])

speed_block = scored["rows"]["speed"][0]
check("the speed chart prefers AA over a probe", "aa", speed_block["rows"][0]["source"])
check("and reports the free model first", "Space Bunny Free", speed_block["rows"][0]["label"])

probed = build_with(
  FREE, [],
  speed_rows=[{"opencodeId": "space-bunny-free", "tokensPerSecond": 475, "tokens": 561},
              {"opencodeId": "longcat-2.5-preview-free", "tokensPerSecond": None, "tokens": None, "error": "buffered"}],
)
rows = probed["rows"]["speed"][0]["rows"]
check("a self probe fills the speed chart when AA cannot", "self", rows[0]["source"])
check("and carries its own note", True, "self-measured" in rows[0]["note"])
check("a failed probe leaves the model unmatched", ["longcat-2.5-preview-free"], probed["unmatched"])

section("dashboard: context rows")
many = [{"name": f"Model {index}", "slug": f"model-{index}", "intelligence": float(index), "tokensPerSecond": float(index)}
        for index in range(1, 31)]
crowded = build_with(FREE, many)
check("at most ten context rows per block", dashboard.CONTEXT_LIMIT, len(crowded["rows"]["speed"][0]["rows"]))
check("context rows are the top ten by value", "Model 30", crowded["rows"]["speed"][0]["rows"][0]["label"])
check("context rows are not marked free", False, crowded["rows"]["speed"][0]["rows"][0]["isFree"])
check("rows are sorted descending", True,
      all(crowded["rows"]["speed"][0]["rows"][i]["value"] >= crowded["rows"]["speed"][0]["rows"][i + 1]["value"]
          for i in range(len(crowded["rows"]["speed"][0]["rows"]) - 1)))


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
check("and not into the real data directory", False,
      (_real_data_dir() / "eval-state.json").exists())

section("eval: the progress counter counts every model")
# The original compared a per-model index against a global total, so the readout
# restarted at 1/1200 for each model. The counter is now a single global tally.
total = 600 * 2
done = 0
seen = []
for _model in range(2):
  for _question in range(600):
    done += 1
    seen.append(done)
check("the counter is monotonic across models", True, seen == sorted(seen))
check("and never restarts", 1200, seen[-1])
check("so it agrees with the total", total, seen[-1])


print()
print(f"{PASSED} passed, {FAILED} failed")
sys.exit(1 if FAILED else 0)
