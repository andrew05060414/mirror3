# Mirror3 — Agent / AI Assistant Guide

Read this file when helping a user install, configure, troubleshoot, or automate **Mirror3** (cross-platform mirror manager). Prefer running commands from the Mirror3 project root unless the user specifies another path.

## Project identity

| Field | Value |
|-------|--------|
| Name | Mirror3 |
| Entry | `mirror3.py` (Python 3.8+, stdlib only) |
| Wrappers | `mirror3` (Unix), `mirror3.bat` (Windows) |
| Catalog | `mirrors.catalog.json` (mirror candidates per tool) |
| Runtime state | `.mirror3/` (backups, health, disabled, reports) |
| Human docs | `docs/GUIDE.zh-CN.md` (detailed, Chinese) |
| Mirror research | `MIRROR_SOURCES.md` |

Default project root example: `/Users/andrewwang/Code/Mirror3` — always resolve from user's actual clone path.

## Design principles (do not violate)

1. **Tool-scoped**: Use `--tools tool1,tool2` — never tell users to "apply everything" unless they explicitly want all tools in catalog.
2. **Non-destructive catalog**: `prune` writes `.mirror3/disabled.json`; it does **not** remove entries from `mirrors.catalog.json`.
3. **Backup before apply**: Real `apply` (without `--dry-run`) creates `.mirror3/backups/<timestamp>/<tool>.json` before overwriting config files.
4. **Dry-run first**: For first-time or risky changes, run `apply --dry-run` and show output before real apply.
5. **No git commits** unless user asks.
6. **Proxy awareness**: If user uses Clash/VPN, speedtest/verify results reflect proxied network; mention this when results look odd.

## Supported tools (catalog)

Typical tools: `bun`, `cargo`, `composer`, `docker`, `gem`, `go`, `gradle`, `homebrew`, `maven`, `npm`, `nuget`, `pip`, `pnpm`, `rustup`, `uv`, `yarn`.

Confirm with: `python3 mirror3.py list-tools`

`homebrew` has empty `config_path` on Windows — expect skip on Windows.

## Command reference (machine-oriented)

All commands: `python3 mirror3.py <subcommand> [options]` from project root.

| Subcommand | Requires `--tools` | Modifies disk | Notes |
|------------|-------------------|---------------|-------|
| `list-tools` | No | No | List catalog tools |
| `list-mirrors --tool X` | `--tool` required | No | Shows `(disabled)` suffix |
| `status` | Optional (default all) | No | Read config files |
| `speedtest` | Optional | No | Skips disabled mirrors |
| `apply` | Optional | Yes (unless `--dry-run`) | Picks fastest or `--prefer` |
| `restore` | Optional | Yes (unless `--dry-run`) | Uses LATEST snapshot if no `--snapshot` |
| `list-snapshots` | No | No | |
| `verify` | Optional | Yes (reports + health) | `--no-update-health` skips health.json |
| `prune` | No | Yes (disabled.json) | Needs health history from verify |
| `list-disabled` | No | No | |
| `refresh --source-url URL` | No | Yes (catalog file) | |
| `schedule` | No | No | Prints cron/Task Scheduler hints |
| `doctor` | Optional | No | Runs external CLIs if installed |

### Global option patterns

- `--tools a,b,c` — comma-separated, no spaces.
- `--prefer tool=mirror,tool=mirror` — mirror `name` from catalog, not URL.
- `--timeout N` — seconds, default 4.
- `--dry-run` — apply/restore only.

### apply selection logic

1. If `--prefer tool=name` for that tool → use that mirror (error if disabled).
2. Else speedtest all non-disabled mirrors → pick lowest score among `ok=True`.
3. If none ok → first non-disabled mirror in catalog (fallback).
4. Merge into config: line-based tools upsert keys; structured formats replace file content.

### verify + prune pipeline

```
verify [--markdown]  →  .mirror3/reports/verify-<ts>.json
                      →  append .mirror3/health.json checks["tool:name"] = [bool,...]

prune --streak N     →  if last N entries in checks[key] are all false
                      →  add to .mirror3/disabled.json
```

`prune --enable tool=mirror` removes from disabled map.  
`prune --clear` empties disabled map.

**Important:** `prune --streak 3` needs at least 3 verify runs with failures for that mirror; first run will often print "No mirrors matched".

### Files touched by apply (macOS examples)

| Tool | Path |
|------|------|
| npm, pnpm, yarn | `~/.npmrc` (`registry=`) |
| bun | `~/.bunfig.toml` |
| pip | `~/.config/pip/pip.conf` |
| uv | `~/.config/uv/uv.toml` |
| go | `~/Library/Application Support/go/env` |
| cargo | `~/.cargo/config.toml` |
| rustup | `~/.zshrc` (RUSTUP_* exports) |
| homebrew | `~/.zshrc` (HOMEBREW_BOTTLE_DOMAIN) |
| maven | `~/.m2/settings.xml` |
| gradle | `~/.gradle/init.gradle` |
| nuget | `~/.nuget/NuGet/NuGet.Config` |
| gem | `~/.gemrc` |
| composer | `~/.config/composer/config.json` |
| docker | `~/.docker/daemon.json` |

Windows paths: see `config_path.windows` in catalog (`%USERPROFILE%`, `%APPDATA%`).

**Shared config warning:** npm/pnpm/yarn share `~/.npmrc` registry line.

## User intent → recommended commands

| User says | Do this |
|-----------|---------|
| "Check my mirrors" | `status` then optionally `list-mirrors --tool X` |
| "Which is fastest?" | `speedtest --tools ... --top 3` |
| "Switch to China mirrors" | `apply --dry-run` then `apply --tools ...` |
| "Only npm and pip" | `apply --tools npm,pip` |
| "Use Tsinghua for pip" | `apply --tools pip --prefer pip=tuna` |
| "Undo last change" | `list-snapshots` → `restore --tools ...` |
| "Clean bad mirrors" | `verify --markdown` → `prune --streak 3` |
| "Re-enable mirror X" | `prune --enable tool=name` |
| "Daily automation" | `schedule` + edit plist/xml paths |
| "Update mirror list from team" | `refresh --source-url ...` |
| "Rust / cargo slow" | `speedtest --tools cargo,rustup` → `apply --tools cargo,rustup` |
| "Docker pull slow" | `apply --tools docker` + remind restart Docker Desktop |

## Standard workflows (copy-paste for users)

### First-time safe apply

```bash
cd <MIRROR3_ROOT>
python3 mirror3.py status --tools npm,pip
python3 mirror3.py speedtest --tools npm,pip --top 2
python3 mirror3.py apply --tools npm,pip --dry-run
python3 mirror3.py apply --tools npm,pip
```

### Maintenance chain (recommended daily)

```bash
python3 mirror3.py verify --markdown
python3 mirror3.py prune --streak 3
python3 mirror3.py apply --tools npm,pnpm,yarn,pip,uv,go,cargo,rustup,docker
```

### Rollback

```bash
python3 mirror3.py restore --tools npm,pip
```

## Troubleshooting decision tree

```
User: apply did nothing / wrong URL
├─ Run: status --tools <tool>
├─ If unchanged: check apply output for "skipped" (platform unsupported / all disabled)
└─ If changed but installs fail: doctor; verify tool-specific env (new shell for rustup/homebrew)

User: all speedtest FAIL
├─ Check proxy env (http_proxy, ALL_PROXY)
├─ Increase --timeout 8
└─ verify --all-mirrors for disabled entries

User: prune never disables
├─ Explain need repeated verify failures
├─ Run verify 3+ times OR lower --streak 2 for testing
└─ inspect .mirror3/health.json

User: docker still slow after apply
└─ Remind: restart Docker Desktop; daemon.json path; some registry mirrors need auth (401 on /v2/ is OK for probe)

User: wants official sources back
├─ restore --tools ...
└─ or apply --prefer npm=npmjs,pip=pypi, etc. (names from list-mirrors)
```

## Customizing catalog (for agents editing JSON)

File: `mirrors.catalog.json` → `tools.<tool>.mirrors[]` each entry:

```json
{ "name": "unique-id", "url": "https://..." }
```

Optional per-tool fields: `config_path`, `format`, `key`, `test_path`.

After edit: `speedtest --tool ...` to validate reachability.

Do not store secrets in catalog URLs.

## Platform invocation

| OS | Command |
|----|---------|
| macOS/Linux | `python3 mirror3.py ...` or `./mirror3 ...` |
| Windows | `python mirror3.py ...` or `mirror3.bat ...` |

## What agents should NOT do

- Do not manually edit user config files when `apply`/`restore` can do it (unless user wants hand-editing).
- Do not delete `.mirror3/backups` without user consent.
- Do not assume `go`/`cargo` installed — `doctor` may fail harmlessly.
- Do not recommend editing `/etc/docker/daemon.json` on macOS (catalog uses `~/.docker/daemon.json` for Docker Desktop).

## Related files to cite to users

- Detailed human tutorial: `docs/GUIDE.zh-CN.md`
- Quick start: `README.md`
- Upstream mirror links: `MIRROR_SOURCES.md`

## Version note

If subcommands in this doc mismatch CLI, run `python3 mirror3.py --help` and trust live help output over this file.
