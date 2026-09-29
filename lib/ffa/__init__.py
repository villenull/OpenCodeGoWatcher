"""Ported from the `free-for-all` Paseo plugin, which is no longer maintained.

Module-for-module against the original `server/`:

| here            | there              |
|-----------------|--------------------|
| `store`         | `server/store.ts`    |
| `opencode`      | `server/opencode.ts` |
| `match`         | `server/match.ts`    |
| `aa`            | `server/aa.ts`       |
| `complete`      | `server/complete.ts` |
| `speed`         | `server/speed.ts`    |
| `omniscience`   | `server/omniscience.ts` |
| `eval`          | `server/eval.ts`     |
| `dashboard`     | `server/dashboard.ts`|

Stdlib only, like the rest of this plugin. The original had no third-party
runtime dependencies either, so nothing had to be substituted.
"""
