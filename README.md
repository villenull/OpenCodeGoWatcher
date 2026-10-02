# My Agents

One Omarchy plugin containing Villenull’s customized AI usage panel and the
OpenCode Go background collector. It displays Claude Code, Codex, Fireworks,
and OpenCode Go usage, limits, history, and model statistics.

The plugin keeps its existing ID, `io.github.villenull.opencode-go-watcher`,
so installations from this repository can update in place. Version 3 bundles
`Panel.qml`, its supporting components and icons, and `Service.qml` in one
plugin. The panel is derived from Omarchy’s MIT-licensed Agents widget.

## Install

```bash
omarchy plugin add https://github.com/villenull/OpenCodeGoWatcher --enable --yes
```

Requires Omarchy 4, Python 3.11+, jq, and your existing provider logins.
The bar widget replaces the stock Agents widget and includes the OpenCode Go
icons. The collector runs every five minutes while the plugin is enabled.

## Upgrade from the separate plugins

Update the existing plugin, then run the included migration:

```bash
omarchy plugin update io.github.villenull.opencode-go-watcher
~/.config/omarchy/plugins/io.github.villenull.opencode-go-watcher/bin/my-agents-migrate
omarchy-shell shell rescanPlugins
```

The migration keeps your panel position and settings, combines the two enabled
entries, and backs up the old clone and shell configuration under
`~/.local/state/my-agents-backups/`. It is safe to run again. The menu then has
one **My Agents** entry.

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

## Development

```bash
./test/usage-test.sh
```

Collector internals and diagnostic commands are documented in
[the collector reference](docs/collector.md). That reference describes the
original service-only installation; the separate panel clone is no longer
needed with version 3.
