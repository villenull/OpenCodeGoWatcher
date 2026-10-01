# OpenCode Go Watcher

**OpenCode Go usage and rate limits in the Omarchy agents panel.**

Omarchy's bar already has a panel that tracks your AI coding subscriptions —
plan, percentage of each allowance used, tokens by day, tokens by model. It
ships collectors for Claude Code, Codex, and Fireworks. OpenCode Go is not one
of them, and it cannot simply be dropped in: the built-in collectors are invoked
by `omarchy-agent-usage-update`, which only ever looks inside the omarchy
package's own `bin/`. This plugin fills the gap and adds an **OpenCode Go** tab
next to the others.

Runs on **Omarchy 4**.

![The OpenCode Go tab](docs/panel.png)

*The OpenCode Go tab. The logo is the optional extra described below — without
it the tab falls back to the panel's bar glyph and looks the same otherwise.*

## What it shows

- **Rate limits** — the percentage used of each window OpenCode Go meters you
  on, and the time until it resets: the rolling 5-hour, the weekly, and the
  monthly.
- **Tokens by day** — one row per day for the last week, today bolded.
- **Tokens by model** — the input / output / cache split, scaled to the heaviest
  model.
- **Prompts and sessions** — today, and all time across every active day.

The monthly window is the one that bites. The 5-hour and weekly meters can both
read zero while you are actually capped, because a free model burns rolling
budget without touching the monthly allowance; only the monthly meter tells the
truth.

## Free-model charts

A second window answers one question: **how do the free models compare with
the models you orchestrate with?** It puts the free models next to Claude Opus
5.5, Claude Sonnet 5.5, GPT-6.1 Sol and GPT-6 Astra at medium effort, plus a few
of Artificial Analysis's top models for scale, on two charts side by side:

| Chart | Paid models | Free models |
|---|---|---|
| **SciCode** (% of sub-problems solved) | published by Artificial Analysis | our own run, the same test the same way |
| **Output speed** (tokens/s) | published by Artificial Analysis | measured locally, the way AA measures |

SciCode asks a model to write real scientific Python, step by step, and runs
the code against the benchmark's tests: a step passes only if every test case
does. Nothing grades it but the tests, so the free models' numbers sit on the
same axis as the published ones. It is part of AA's Intelligence Index, and the
closest of its tests to what a coding worker does that can be run here.

The orchestrators are set in code (`DEFAULT_ORCHESTRATORS` in
`lib/ffa/dashboard.py`), or with `"orchestrators": ["claude-opus-5-5-medium", …]`
in `~/.config/opencode-go-watcher/settings.json`, using Artificial Analysis's
model slugs.

Open it from the OpenCode Go tab in the agents panel — the **Free-model charts
& eval** button — or directly:

```bash
omarchy-shell opencode-go-watcher.charts open
```

Note the target: `opencode-go-watcher.charts`, **not**
`omarchy-shell shell summon io.github.villenull.opencode-go-watcher`. The panel
owns an IPC target of its own, and the reason is a real bug.

`summon` sets the shell's `openPanelIds[pluginId] = true` and hands the payload
to the plugin through its Loader, which is active only while that id is set
(`shell.qml:1337`). Close the window with `SUPER + W` and the compositor
destroys the surface, which tears the Loader down. The panel's `onVisibleChanged`
does call back `shell.hide()`, but the next `summon` still queues a payload that
nobody delivers: **the button stops working until the shell is reloaded.** The
manifest sets `keepLoaded: true`, so the panel component stays mounted whatever
the registry says, and its own handler is always live. `open` there is
idempotent — it can only ever open, never toggle a stale entry shut.

### The button is a local patch

The `summon` line above is the whole integration, and it is one line of QML
added to a **clone** of the built-in agents panel — the panel has no extension
point for action buttons, and a provider record only carries limits and token
stats. This plugin cannot ship that patch, because `/usr/share/omarchy/` is
package-owned, so the clone is the price of the button:

```bash
omarchy plugin clone omarchy.agents   # lands as villenull.agents
```

Then add to `~/.config/omarchy/plugins/villenull.agents/Panel.qml`, above the
`// ---------- Balance / limits ----------` separator:

```qml
Column {
  visible: !!root.provider && root.provider.providerId === "opencode-go"
  width: parent.width
  Button {
    text: "Free-model charts & eval"
    bordered: true
    onClicked: {
      root.close()
      freeForAllSummon.command = ["omarchy-shell", "shell", "summon",
                                  "io.github.villenull.opencode-go-watcher", "{}"]
      freeForAllSummon.running = true
    }
  }
}
Process {
  id: freeForAllSummon
  stderr: StdioCollector {
    waitForEnd: true
    onStreamFinished: if (text.trim() !== "") console.warn("opencode-go-watcher", text.trim())
  }
}
```

Two consequences worth stating plainly. The clone will not receive upstream fixes
to the panel, so any `omarchy update` that touches it becomes yours to merge.
And the button is scoped to the `opencode-go` provider, so it never appears on
another subscription. If you would rather not carry the clone, skip all of this
and use the `summon` line — which is also the only thing the plugin itself
depends on.

### Why the window is a toplevel, and how to close it

The window is a Quickshell `FloatingWindow`, not a `PanelWindow`, and that is
load-bearing rather than a style choice. Omarchy's other centred windows are
`FloatingWindow`s: they are real toplevels, so Hyprland makes one the active
window and `SUPER + W` — which is `hl.dsp.window.close()` — closes it. A
`PanelWindow` is layer-shell, has no toplevel for the compositor to focus, and
is therefore invisible to every window binding: it can only be dismissed by a
keypress the surface happens to hold keyboard focus for, which is a much weaker
guarantee.

Two ways to close it: `SUPER + W` and `Escape`. There is no Close button — the
window is a normal toplevel, so the desktop's own close binding is the right one
and a second control in the corner is noise. `Escape` is the fallback for when
the window has not been focused yet, which a freshly summoned window may not
have been.

### No Hyprland config needed

A toplevel is not automatically an overlay: without a window rule Hyprland
tiles it beside your terminals. The plugin registers that rule itself, at
runtime, each time the window opens — the same way `omarchy-launch-about`
sizes the About window — so nothing is written to your Hyprland config:

```lua
hl.window_rule({
  match = { class = "^org\\.quickshell$", title = "^OpenCode Go free models$" },
  float = true, center = true, size = { W, H },
  tag = "-default-opacity", opacity = "1 1",
})
```

The window stays hidden until `hyprctl eval` has returned, because rules only
apply when a window is mapped. The result behaves like About: it opens in the
middle of the workspace you are on, `SUPER` + drag moves it, and it stays on
that workspace when you switch away (there is deliberately no `pin`).

| Option | Why |
|---|---|
| `float`, `center` | an overlay in the middle of the screen, not a tile |
| `size` | the window surface *is* the card; taken from the QML so the two never disagree |
| `tag`, `opacity` | omarchy tags every window `+default-opacity` and applies `0.985 0.96`. Removing the tag alone does nothing — omarchy's own `qemu` rule pairs it with `opacity = "1 1"`, and so must this. At 0.96 the text behind reads through the chart as ghosting |

The match is on class **and** title because `org.quickshell` is every
Quickshell toplevel, omarchy's own included. Each open replaces the previous
rule rather than stacking another.

Verify with `hyprctl clients -j | jq '.[] | select(.title|test("free models"))'`
— you want `"floating":true` and `"pinned":false`.

A note on contrast, if you restyle it: the panel does not use the theme's
`muted` token. On a stock theme that is `#707880` on `#101315`, and
`PanelSectionHeader` paints in `Qt.darker(foreground, 1.4)` — dimmer still — so
a chart built from those reads as decorative rather than numeric. The window
declares one ramp of lifted foregrounds instead and threads it into the rows, so
secondary text keeps the theme's hue and stays readable. Change the ramp in one
place rather than per widget.

The two charts are deliberately **not** on one axis: they are different
scales. In every row, an **accent** name is a free model, a **bold** one is one
of your orchestrators and a **dim** one is AA's top models for scale; a filled
bar is a published number and an outlined one was measured by this plugin.

### The SciCode run

**Run SciCode** benchmarks every free model the way Artificial Analysis does:

- the **288 scored sub-problems** of SciCode's test split (65 problems; the
  three steps the official harness never asks for are given, not scored);
- the **scientist-annotated background** prompt, word for word;
- each step is shown the model's **own code** for the earlier steps of its
  problem, so a problem's steps run in order;
- **medium reasoning effort**, like the orchestrators on the chart and like
  OpenCode's own `medium` variant; at the API's default Space Bunny spent its
  whole 16,000-token budget thinking about one step and wrote no code;
- each step's script has the **300-second timeout** AA uses.

**It costs nothing but time.** The free models answer through your Go key, and
there is no grader to pay for. A run is one call per step plus running the
code — roughly an hour or more per free model, four problems at a time. It runs
as a detached process, so closing the window or reloading the shell doesn't
stop it, and a run that does stop picks up where it left off next time.

**The first run downloads two things** into the plugin's state directory:
SciCode's numeric test targets (1 GB, from a pinned and checksummed Hugging
Face copy, since the authors host the original on Google Drive) and a private
Python environment with numpy, scipy, sympy, h5py and matplotlib (~150 MB).

**Model-written code runs sealed off** under bubblewrap: no network, your home
directory replaced by an empty one, and only that environment, the targets and
SciCode's helpers visible, read-only. A step that allocates more than 8 GB is
stopped.

The harness checks itself: `opencode-go-watcher-free-for-all-eval verify` runs
the official solutions of SciCode's 15-problem practice split through it. 48 of
the 50 pass; the other two fail outside the sandbox too, so the fault is in
SciCode's own data. Current numpy and scipy dropped a few names SciCode's
problems were written against (two problems import `scipy.integrate.simps`), so
`lib/scicode_support/sitecustomize.py` puts each back as its documented
replacement.

### Data sources

| What | Where it comes from |
|---|---|
| Paid models: SciCode, speed | artificialanalysis.ai, the public website |
| Free models: SciCode | our own run (the Run SciCode button) |
| Free models: speed | a local probe on your Go key (the Measure speed button) |
| Free-model list | the opencode Go catalogue, no key needed |

No Artificial Analysis key is needed. AA's free API returns only composite
indices and not every effort level, but any model page on their website embeds
a record for every model they track — each effort level separately — with its
index, speed and per-evaluation scores. `lib/ffa/aaweb.py` reads those records
and caches them for a day. It is a page, not an API with a contract, so parsing
is defensive: if the page can't be read the last good copy is used and the
window says so. The Refresh button re-reads it.

### Measuring speed honestly

The probe asks each free model to count, three times, and divides its output
tokens by the **generation window** — first streamed token to last, so time to
first token is excluded — then takes the median. That is how Artificial
Analysis measures it, which is the only reason the two numbers can share an
axis.

The window starts at the first token **of any kind**. A reasoning model streams
its hidden thinking first, and the token count includes it; timing only the
visible answer divided all of it by the last second of output, and showed
Space Bunny at 261 tok/s (621 in a single sample) when it runs at about 140.

Two things it refuses to do:

- **It does not reuse a prompt across samples.** An identical prompt hits
  opencode's prompt cache, and a cached sample's "speed" is an artefact of the
  cache. Taking the median of one real sample and one cached sample produced a
  figure in the hundreds of thousands — faster than light, and obviously wrong.
- **It will not publish a number it cannot defend.** The gateway sometimes
  delivers a whole completion in a single read, in which case there is no
  generation window to measure. That sample is discarded and the row falls back
  to AA's published figure; if every sample is unusable the row says so rather
  than inventing a number.

## Install

```bash
omarchy plugin add https://github.com/villenull/OpenCodeGoWatcher --enable
~/.config/omarchy/plugins/io.github.villenull.opencode-go-watcher/bin/opencode-go-watcher-setup
```

`omarchy plugin update` keeps the checkout current, so there is a single copy on
disk.

The second command checks the setup and changes nothing: your opencode Go key
(the free models answer with it), bubblewrap (SciCode runs model-written code
under it), whether SciCode's data is downloaded, and whether speed and SciCode
have been run. There is nothing to configure.

```bash
.../bin/opencode-go-watcher-setup                 # check the setup
.../bin/opencode-go-watcher-setup --probe-speed    # measure speed now
.../bin/opencode-go-watcher-setup --clear-aa-key   # remove a key an older version stored
```

The free-model charts window needs no Hyprland config; see
[*No Hyprland config needed*](#no-hyprland-config-needed).

Then sign in to OpenCode Go if you have not already — `opencode auth login`, or
any `opencode-go` model in opencode itself. The tab appears on the next
refresh; press `r` in the panel, or wait for the next publish.

Requires Python 3.11+ (both omarchy's own collectors and this one use it) and
`jq`, which Omarchy already requires. Nothing else to install: the backend is
stdlib-only.

### The tab has no logo

The panel draws a provider's mark from `assets/<id>.svg` inside its own
directory, which for the built-in panel is a path the omarchy package owns.
Shipping a logo would mean shipping a fork of the panel, and a fork does not
receive upstream fixes — a bad trade for one icon. So this tab falls back to
the panel's own bar glyph, which is the documented behaviour for a provider
that ships no mark.

If you want the OpenCode mark anyway, and accept maintaining the fork:

```bash
omarchy plugin clone omarchy.agents
cp ~/.config/omarchy/plugins/villenull.agents/assets/opencode-go{,-light}.svg \
   ~/.config/omarchy/plugins/villenull.agents/assets/
```

Undo it with `omarchy plugin remove villenull.agents`, which puts
`omarchy.agents` back in the bar; the OpenCode Go tab survives either way.

## Uninstall

Two steps, in this order:

```bash
~/.config/omarchy/plugins/io.github.villenull.opencode-go-watcher/bin/opencode-go-watcher-uninstall
omarchy plugin remove io.github.villenull.opencode-go-watcher
```

The first command is not optional bookkeeping. This plugin publishes a record
into `~/.local/state/omarchy/agents/usage/`, which the stock panel treats as its
own — it `find`s every `*.json` there and draws whatever it finds, with no
record of who wrote it. `omarchy plugin remove` deletes the checkout and the
`shell.json` entry; it cannot know about that file. So removing the plugin on
its own leaves the OpenCode Go tab in your bar **frozen** at whatever the
service last wrote, surviving reboots, with nothing left to update it. The
uninstall script removes the record and this agent's scan caches, and leaves the
other agents' caches alone.

It has to run first: once the checkout is gone, so is the script. If you already
removed the plugin, the equivalent is one line:

```bash
rm -f ~/.local/state/omarchy/agents/usage/opencode-go.json \
      ~/.cache/omarchy/agent-usage/opencode-go-*
```

Either way the panel drops the tab on its next rescan, or immediately with
`omarchy-shell omarchy.agents refresh`.

## How it works

`omarchy.agents` is strictly a display. It watches
`~/.local/state/omarchy/agents/usage/` and draws whatever records it finds
there — a record that appears in that directory is an agent, whoever wrote it.
So this plugin writes a record and stays out of the panel's way; the panel
itself is never modified.

A five-minute service runs the collector and publishes the result atomically.
The collector reads two places:

| Field | Source |
|---|---|
| Tokens, prompts, sessions, models | `~/.local/share/opencode/opencode.db` — every `role: "assistant"` message whose `providerID` is exactly `opencode-go` |
| Rate-limit windows | `GET https://opencode.ai/zen/go/v1/usage`, authenticated with the key from `OPENCODE_API_KEY` or opencode's own `auth.json` |

Provider matching is exact, as it is in the built-in claude and codex
collectors: an `opencode-go-proxy` gateway or a plain `opencode` provider is a
different subscription and stays out. That is also why this plugin has to exist
at all — the built-in collectors do scan `opencode.db`, but only for the
`anthropic` and `openai` providers, so OpenCode Go's usage was previously
counted nowhere.

### Performance

opencode's database is large — tens of gigabytes on a machine that has been
coding for a while — so the scan is not free. Two things keep it cheap:

- The SQL query filters with `LIKE` gates and `json_extract` before any row
  reaches Python, so non-matching JSON is never parsed. A cold scan over a 16 GB
  database takes about 0.6 s.
- The result is cached in `~/.cache/omarchy/agent-usage/`, keyed by database
  path and stamped with the day it was taken, so `--limits-only` can reuse a
  scan for 15 minutes and a normal run reuses one only long enough (20 s) to
  dedup two collectors racing.

## Commands

`bin/` is not on `PATH`, so the plugin path is spelled out:

```bash
# what the panel is currently drawing
~/.config/omarchy/plugins/io.github.villenull.opencode-go-watcher/bin/opencode-go-watcher-status

# ...after collecting fresh data
.../bin/opencode-go-watcher-status --refresh

# the raw record
.../bin/opencode-go-watcher-status --json

# publish now instead of waiting for the timer
.../bin/opencode-go-watcher-publish

# the collector on its own: one display-ready JSON record on stdout
.../bin/opencode-go-watcher-usage
.../bin/opencode-go-watcher-usage --force        # rescan past the cache
.../bin/opencode-go-watcher-usage --limits-only  # fresh limits, cached stats
```

`opencode-go-watcher-status` reads the published record rather than collecting,
so asking a question does not cost a walk over the database. `--refresh` is the
only way to see a window that moved since the last publish.

`OPENCODE_GO_USAGE_URL` overrides the usage endpoint, which is how the test
exercises the limits handling without a network.

The free-model charts have their own commands:

```bash
P=~/.config/omarchy/plugins/io.github.villenull.opencode-go-watcher

# the snapshot the window draws, as JSON
$P/bin/opencode-go-watcher-free-for-all
$P/bin/opencode-go-watcher-free-for-all --force   # skip the six-hour cache

# measure output speed for every free model (spends a little Go quota)
$P/bin/opencode-go-watcher-free-for-all-speed
$P/bin/opencode-go-watcher-free-for-all-speed --model space-bunny-free

# the SciCode benchmark
$P/bin/opencode-go-watcher-free-for-all-eval start                          # every free model
$P/bin/opencode-go-watcher-free-for-all-eval start --model space-bunny-free # just one
$P/bin/opencode-go-watcher-free-for-all-eval status       # progress
$P/bin/opencode-go-watcher-free-for-all-eval cancel       # stop; the next start resumes
$P/bin/opencode-go-watcher-free-for-all-eval verify       # check the harness on SciCode's official solutions
```

## When the tab is missing

The panel hides an agent that has produced no numbers, so an empty tab usually
means one of:

- **Not signed in.** No key in `auth.json` and no `OPENCODE_API_KEY`. The
  collector says so in the record's `authHelpText`; the panel shows that line.
- **No OpenCode Go usage yet.** The tab appears the moment a scan finds one
  assistant message on the `opencode-go` provider.
- **Disabled in the widget settings.** The publisher reads the panel's own
  per-agent switch and stops writing, so re-enabling there is enough:

  ```bash
  omarchy bar set omarchy.agents providers '{
    "claude": { "enabled": true },
    "codex": { "enabled": true },
    "fireworks": { "enabled": true },
    "opencode-go": { "enabled": true }
  }' --json
  ```

`omarchy-shell omarchy.agents refresh` forces a republish of the other three
and makes the panel rescan for records, which is the fastest way to make a
missing tab appear once the data is there.

## Tests

```bash
./test/usage-test.sh        # 16 — the usage record and the limits endpoint
./test/free-for-all-test.py # 167 — the charts, the SciCode harness and the speed probe
```

Neither touches the network, and neither writes outside a temporary directory —
the dashboard tests build real snapshots, so an un-sandboxed run would overwrite
your own with fixtures and the window would then render `Model 30` as though it
were a leaderboard. (That is not hypothetical; it is why the suite sandboxes
`store.data_dir`.)

`usage-test.sh` covers the usage record over a throwaway fixture: that the
collector counts `opencode-go` messages and nothing that merely looks like one, that reasoning
folds into output while cache stays separate, that a corrupt row does not abort
a scan, that the cache is reused by `--limits-only` and bypassed by `--force`,
and that percentages arriving as `0..100` leave as `0..1`. The network is
stubbed, so the suite never depends on a live subscription or on the developer's
own usage.

## Provenance

The free-model charts are a port of the `free-for-all` Paseo plugin, which is no
longer maintained and had stopped loading: Paseo's RPC layer validates method
names against `/^[a-z][a-z0-9._-]*$/` and every one of its six was named
`freeForAll.*`, so the plugin failed to load on the 0.10.1 daemon and the whole
feature was unreachable. Its source is kept at
`~/.local/share/Trash/files/paseo-plugins/free-for-all` if you want to diff
against it.

What changed in the port, beyond the move to Python:

- **The eval survives a shell reload.** Run state was a module global, so a run
  that outlived a plugin reload had nobody left to report it — it kept spending
  2,400 calls invisibly and could not be cancelled. State now lives in
  `eval-state.json`, and a run whose process is gone is reported as interrupted
  rather than as running forever.
- **The progress counter counts across models.** It compared a per-model index
  against a global total, so the readout walked 1/1200 … 600/1200 and then
  restarted at 1/1200 for the next model.
- **The speed probe stopped publishing artefacts.** See *Measuring speed
  honestly* above; the original's identical-prompt samples were hitting the
  prompt cache.
- **Every write is atomic, and the AA key file is `0600`.** Four of the original's
  five data files were written in place, so a reader landing mid-write saw
  truncated JSON, and the one holding the API key was created without a mode.
- **An empty chart says so.** With no AA key the block rendered as a blank card,
  which read as broken rather than as nothing measured yet.

The port originally measured the free models on AA-Omniscience, a knowledge
quiz graded by Big Pickle on a 100-question sample. Version 1.3 replaced it with
SciCode: it is about writing code, it is graded by running tests rather than by
another model, and the full 288-step run matches what AA publishes.


The collector is ported from
[basecamp/omarchy#7157](https://github.com/basecamp/omarchy/pull/7157), an open
pull request adding OpenCode Go support to the built-in panel. It is not merged,
and several rival PRs cover the same ground, so it may never be. If it lands
upstream, this plugin becomes redundant — `omarchy plugin remove
io.github.villenull.opencode-go-watcher` and the stock collector takes over the
same tab, because both write the same `opencode-go` record.

One change from upstream: the stale-limits cache drops windows whose reset time
has already passed, so an outage cannot leave a meter describing an allowance
that has since reset.

## License

[MIT](LICENSE).
