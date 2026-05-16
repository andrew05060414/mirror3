#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


DEFAULT_TIMEOUT = 4.0
SPEEDTEST_BYTES = 64 * 1024
BACKUP_DIR_NAME = ".mirror3/backups"
REPORTS_DIR_NAME = ".mirror3/reports"
CATALOG_FILENAME = "mirrors.catalog.json"
HEALTH_FILENAME = ".mirror3/health.json"
DISABLED_FILENAME = ".mirror3/disabled.json"
HEALTH_MAX_CHECKS_PER_MIRROR = 30


@dataclass
class ProbeResult:
    name: str
    url: str
    ok: bool
    latency_ms: float
    download_mbps: float
    score: float
    error: str = ""


def _platform() -> str:
    p = platform.system().lower()
    if "windows" in p:
        return "windows"
    if "darwin" in p:
        return "macos"
    return "linux"


def _is_wsl() -> bool:
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False


def _path_parent_writable(path: Path) -> bool:
    parent = path.parent
    for _ in range(32):
        if parent.exists():
            return os.access(parent, os.W_OK)
        if parent == parent.parent:
            break
        parent = parent.parent
    return False


def _home() -> Path:
    return Path.home()


def _catalog_path(project_root: Path) -> Path:
    return project_root / CATALOG_FILENAME


def _backup_root(project_root: Path) -> Path:
    return project_root / BACKUP_DIR_NAME


def _mirror3_dir(project_root: Path) -> Path:
    return project_root / ".mirror3"


def _health_path(project_root: Path) -> Path:
    return project_root / HEALTH_FILENAME


def _disabled_path(project_root: Path) -> Path:
    return project_root / DISABLED_FILENAME


def _reports_dir(project_root: Path) -> Path:
    return project_root / REPORTS_DIR_NAME


def load_disabled(project_root: Path) -> Dict[str, set]:
    p = _disabled_path(project_root)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    out: Dict[str, set] = {}
    for tool, names in raw.get("disabled", {}).items():
        if isinstance(names, list):
            out[tool] = {str(x) for x in names}
    return out


def save_disabled(project_root: Path, disabled: Dict[str, set]) -> None:
    _ensure_parent(_disabled_path(project_root))
    payload = {
        "version": 1,
        "disabled": {k: sorted(v) for k, v in sorted(disabled.items()) if v},
    }
    _disabled_path(project_root).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_health(project_root: Path) -> Dict:
    p = _health_path(project_root)
    if not p.exists():
        return {"version": 1, "checks": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "checks": {}}


def save_health(project_root: Path, health: Dict) -> None:
    _ensure_parent(_health_path(project_root))
    _health_path(project_root).write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _health_key(tool: str, mirror_name: str) -> str:
    return f"{tool}:{mirror_name}"


def update_health_checks(
    project_root: Path,
    tool: str,
    results_by_name: Dict[str, bool],
) -> None:
    health = load_health(project_root)
    health.setdefault("version", 1)
    health.setdefault("checks", {})
    checks: Dict[str, List] = health["checks"]
    for name, ok in results_by_name.items():
        key = _health_key(tool, name)
        seq = checks.get(key)
        if not isinstance(seq, list):
            seq = []
        seq.append(bool(ok))
        if len(seq) > HEALTH_MAX_CHECKS_PER_MIRROR:
            seq = seq[-HEALTH_MAX_CHECKS_PER_MIRROR:]
        checks[key] = seq
    save_health(project_root, health)


def mirror_entry_disabled(tool: str, entry: Dict, disabled_map: Dict[str, set]) -> bool:
    if entry.get("disabled") is True:
        return True
    return entry.get("name") in disabled_map.get(tool, set())


def yield_visible_mirrors(
    tool: str,
    cfg: Dict,
    disabled_map: Dict[str, set],
    *,
    include_disabled: bool,
) -> List[Dict]:
    out: List[Dict] = []
    for m in cfg.get("mirrors", []):
        if not isinstance(m, dict) or "name" not in m:
            continue
        if not include_disabled and mirror_entry_disabled(tool, m, disabled_map):
            continue
        out.append(m)
    return out


def load_catalog(project_root: Path) -> Dict:
    p = _catalog_path(project_root)
    if not p.exists():
        raise FileNotFoundError(
            f"Missing catalog file: {p}. Please keep {CATALOG_FILENAME} next to mirror3.py"
        )
    return json.loads(p.read_text(encoding="utf-8"))


def expand_path(path_expr: str) -> Path:
    return Path(os.path.expandvars(path_expr)).expanduser()


def candidate_tools(catalog: Dict) -> List[str]:
    return sorted(catalog["tools"].keys())


def parse_tools(arg_tools: Optional[str], catalog: Dict) -> List[str]:
    all_tools = candidate_tools(catalog)
    if not arg_tools:
        return all_tools
    chosen = [x.strip() for x in arg_tools.split(",") if x.strip()]
    unknown = [x for x in chosen if x not in all_tools]
    if unknown:
        raise ValueError(f"Unknown tools: {', '.join(unknown)}. Available: {', '.join(all_tools)}")
    return chosen


def _tool_path_expr(tool_cfg: Dict, os_name: str) -> Optional[str]:
    path_map = tool_cfg.get("config_path", {})
    if _is_wsl():
        wsl_expr = path_map.get("wsl")
        if wsl_expr:
            return wsl_expr
    return path_map.get(os_name)


def resolve_config_path(tool: str, tool_cfg: Dict, os_name: str) -> Optional[Path]:
    expr = _tool_path_expr(tool_cfg, os_name)
    if not expr:
        return None
    path = expand_path(expr)
    if tool == "docker" and os_name == "linux":
        path_map = tool_cfg.get("config_path", {})
        user_expr = path_map.get("wsl") or "~/.docker/daemon.json"
        if _is_wsl() or (str(path).startswith("/etc/") and not _path_parent_writable(path)):
            path = expand_path(user_expr)
    return path


def _tool_test_path(tool_cfg: Dict) -> str:
    return tool_cfg.get("test_path", "/")


def _tool_apply_format(tool_cfg: Dict) -> str:
    return tool_cfg.get("format", "line_kv")


def _tool_key(tool_cfg: Dict) -> str:
    return tool_cfg.get("key", "registry")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    try:
        _ensure_parent(path)
    except OSError as e:
        raise OSError(f"cannot create parent directory for {path}: {e}") from e
    try:
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        raise OSError(f"cannot write {path}: {e}") from e


def _render_config(tool: str, tool_cfg: Dict, mirror_url: str) -> str:
    fmt = _tool_apply_format(tool_cfg)
    if fmt == "line_kv":
        key = _tool_key(tool_cfg)
        return f"{key}={mirror_url}\n"
    if fmt == "ini_global":
        key = _tool_key(tool_cfg)
        return f"[global]\n{key} = {mirror_url}\n"
    if fmt == "toml_uv":
        return (
            "[[index]]\n"
            f'name = "auto"\n'
            f'url = "{mirror_url}"\n'
            "default = true\n"
        )
    if fmt == "toml_bun":
        return (
            "[install]\n"
            f'registry = "{mirror_url}"\n'
        )
    if fmt == "docker_daemon":
        payload = {"registry-mirrors": [mirror_url]}
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if fmt == "maven_settings":
        return (
            '<settings xmlns="http://maven.apache.org/SETTINGS/1.2.0"\n'
            '          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
            '          xsi:schemaLocation="http://maven.apache.org/SETTINGS/1.2.0 https://maven.apache.org/xsd/settings-1.2.0.xsd">\n'
            "  <mirrors>\n"
            "    <mirror>\n"
            "      <id>mirror3-central</id>\n"
            "      <name>Mirror3 Managed Mirror</name>\n"
            f"      <url>{mirror_url}</url>\n"
            "      <mirrorOf>central</mirrorOf>\n"
            "    </mirror>\n"
            "  </mirrors>\n"
            "</settings>\n"
        )
    if fmt == "env_line":
        key = _tool_key(tool_cfg)
        return f"export {key}={mirror_url}\n"
    if fmt == "toml_cargo":
        return (
            "[source.crates-io]\n"
            'replace-with = "mirror3"\n'
            "\n"
            "[source.mirror3]\n"
            f'registry = "{mirror_url}"\n'
        )
    if fmt == "gradle_init":
        return (
            "allprojects {\n"
            "    repositories {\n"
            "        mavenLocal()\n"
            f'        maven {{ url "{mirror_url}" }}\n'
            "        mavenCentral()\n"
            "        google()\n"
            "    }\n"
            "}\n"
        )
    if fmt == "nuget_config":
        return (
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
            "<configuration>\n"
            "  <packageSources>\n"
            "    <clear />\n"
            f"    <add key=\"mirror3\" value=\"{mirror_url}\" />\n"
            "  </packageSources>\n"
            "</configuration>\n"
        )
    if fmt == "gemrc":
        return f"---\n:sources:\n- {mirror_url}\n"
    if fmt == "composer_config":
        payload = {
            "repositories": {
                "packagist": {
                    "type": "composer",
                    "url": mirror_url,
                }
            }
        }
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if fmt == "rustup_env":
        return (
            f"export RUSTUP_DIST_SERVER={mirror_url}\n"
            f"export RUSTUP_UPDATE_ROOT={mirror_url.rstrip('/')}/rustup\n"
        )
    raise ValueError(f"Unsupported format for tool={tool}: {fmt}")


def _upsert_line(content: str, key_prefix: str, new_line: str) -> str:
    lines = content.splitlines()
    replaced = False
    out: List[str] = []
    for line in lines:
        clean = line.strip()
        if clean.startswith(key_prefix):
            if not replaced:
                out.append(new_line)
                replaced = True
            continue
        out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(new_line)
    return "\n".join(out).rstrip("\n") + "\n"


def _merge_config(tool_cfg: Dict, old_content: str, mirror_url: str) -> str:
    fmt = _tool_apply_format(tool_cfg)
    key = _tool_key(tool_cfg)
    if fmt == "line_kv":
        return _upsert_line(old_content, f"{key}=", f"{key}={mirror_url}")
    if fmt == "env_line":
        return _upsert_line(old_content, f"export {key}=", f"export {key}={mirror_url}")
    if fmt == "rustup_env":
        merged = _upsert_line(old_content, "export RUSTUP_DIST_SERVER=", f"export RUSTUP_DIST_SERVER={mirror_url}")
        merged = _upsert_line(
            merged,
            "export RUSTUP_UPDATE_ROOT=",
            f"export RUSTUP_UPDATE_ROOT={mirror_url.rstrip('/')}/rustup",
        )
        return merged
    # For structured formats, keep deterministic generated content.
    return _render_config("tool", tool_cfg, mirror_url)


def _extract_current(tool: str, tool_cfg: Dict, content: str) -> str:
    fmt = _tool_apply_format(tool_cfg)
    key = _tool_key(tool_cfg)
    if not content.strip():
        return "(empty)"
    if fmt in {"line_kv", "env_line"}:
        for line in content.splitlines():
            clean = line.strip()
            if clean.startswith("#"):
                continue
            if fmt == "env_line":
                marker = f"export {key}="
            else:
                marker = f"{key}="
            if clean.startswith(marker):
                return clean.split("=", 1)[1].strip()
        return "(configured but not recognized)"
    if fmt == "ini_global":
        for line in content.splitlines():
            clean = line.strip()
            if clean.lower().startswith(f"{key.lower()}"):
                parts = clean.split("=", 1)
                if len(parts) == 2:
                    return parts[1].strip()
        return "(configured but not recognized)"
    if fmt in {"toml_uv", "toml_cargo", "toml_bun"}:
        for line in content.splitlines():
            clean = line.strip()
            if clean.startswith("url") or clean.startswith("registry"):
                parts = clean.split("=", 1)
                if len(parts) == 2:
                    return parts[1].strip().strip('"')
        return "(configured but not recognized)"
    if fmt == "docker_daemon":
        try:
            payload = json.loads(content)
            mirrors = payload.get("registry-mirrors", [])
            if mirrors:
                return ", ".join(mirrors)
            return "(configured no registry-mirrors)"
        except json.JSONDecodeError:
            return "(invalid json)"
    if fmt == "maven_settings":
        needle = "<url>"
        for line in content.splitlines():
            clean = line.strip()
            if needle in clean and "</url>" in clean:
                return clean.replace("<url>", "").replace("</url>", "").strip()
        return "(configured but not recognized)"
    if fmt == "gradle_init":
        needle = 'maven { url "'
        for line in content.splitlines():
            clean = line.strip()
            if needle in clean and '" }' in clean:
                return clean.split(needle, 1)[1].rsplit('"', 1)[0]
        return "(configured but not recognized)"
    if fmt == "nuget_config":
        marker = 'value="'
        for line in content.splitlines():
            clean = line.strip()
            if "<add " in clean and marker in clean:
                return clean.split(marker, 1)[1].split('"', 1)[0]
        return "(configured but not recognized)"
    if fmt == "gemrc":
        for line in content.splitlines():
            clean = line.strip()
            if clean.startswith("- http"):
                return clean.removeprefix("- ").strip()
        return "(configured but not recognized)"
    if fmt == "composer_config":
        try:
            payload = json.loads(content)
            return payload.get("repositories", {}).get("packagist", {}).get("url", "(configured but not recognized)")
        except json.JSONDecodeError:
            return "(invalid json)"
    if fmt == "rustup_env":
        dist = ""
        update = ""
        for line in content.splitlines():
            clean = line.strip()
            if clean.startswith("export RUSTUP_DIST_SERVER="):
                dist = clean.split("=", 1)[1].strip()
            if clean.startswith("export RUSTUP_UPDATE_ROOT="):
                update = clean.split("=", 1)[1].strip()
        if dist or update:
            return f"DIST={dist or '(unset)'} UPDATE_ROOT={update or '(unset)'}"
        return "(configured but not recognized)"
    return "(unknown format)"


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _save_backup(project_root: Path, tool: str, cfg_path: Path, previous_content: str) -> str:
    snap = _timestamp()
    root = _backup_root(project_root) / snap
    root.mkdir(parents=True, exist_ok=True)
    payload = {
        "tool": tool,
        "path": str(cfg_path),
        "content": previous_content,
    }
    (root / f"{tool}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    latest = _backup_root(project_root) / "LATEST"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(snap, encoding="utf-8")
    return snap


def _latest_snapshot(project_root: Path) -> Optional[str]:
    p = _backup_root(project_root) / "LATEST"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").strip()


def _load_backup(project_root: Path, snapshot: str, tool: str) -> Optional[Dict]:
    p = _backup_root(project_root) / snapshot / f"{tool}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def list_tools_cmd(catalog: Dict) -> int:
    print("Supported tools:")
    for t in candidate_tools(catalog):
        print(f"  - {t}")
    return 0


def status_cmd(project_root: Path, catalog: Dict, tools: List[str]) -> int:
    os_name = _platform()
    print(f"Platform: {os_name}" + (" (WSL)" if _is_wsl() else ""))
    for tool in tools:
        cfg = catalog["tools"][tool]
        p = resolve_config_path(tool, cfg, os_name)
        if p is None:
            print(f"[{tool}] not supported on {os_name}")
            continue
        content = _read_if_exists(p)
        current = _extract_current(tool, cfg, content)
        exists = "yes" if p.exists() else "no"
        print(f"[{tool}] file={p} exists={exists} current={current}")
    return 0


def _test_one(name: str, base_url: str, path: str, timeout: float) -> ProbeResult:
    probe_base = base_url
    if "," in probe_base:
        probe_base = probe_base.split(",", 1)[0].strip()
    if probe_base.startswith("sparse+https://"):
        probe_base = probe_base.removeprefix("sparse+")
    test_url = probe_base.rstrip("/") + path
    t0 = time.perf_counter()
    req = urllib.request.Request(test_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            code = getattr(resp, "status", None) or resp.getcode()
            # Docker Registry v2 root often returns 401 without auth — still "reachable".
            if code == 401 and "/v2" in path:
                first = time.perf_counter()
                latency_ms = (first - t0) * 1000
                return ProbeResult(
                    name=name,
                    url=base_url,
                    ok=True,
                    latency_ms=latency_ms,
                    download_mbps=0.0,
                    score=latency_ms + 200.0,
                )
            first = time.perf_counter()
            data = resp.read(SPEEDTEST_BYTES)
            done = time.perf_counter()
            latency_ms = (first - t0) * 1000
            duration = max(done - first, 1e-6)
            mbps = (len(data) * 8 / 1_000_000) / duration
            score = latency_ms + (200 / max(mbps, 0.01))
            return ProbeResult(name=name, url=base_url, ok=True, latency_ms=latency_ms, download_mbps=mbps, score=score)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ValueError) as e:
        return ProbeResult(
            name=name,
            url=base_url,
            ok=False,
            latency_ms=99999.0,
            download_mbps=0.0,
            score=99999.0,
            error=str(e),
        )


def speedtest_tool(
    tool: str,
    cfg: Dict,
    timeout: float,
    disabled_map: Optional[Dict[str, set]] = None,
    *,
    include_disabled: bool = False,
) -> List[ProbeResult]:
    test_path = _tool_test_path(cfg)
    dmap = disabled_map or {}
    mirrors = yield_visible_mirrors(tool, cfg, dmap, include_disabled=include_disabled)
    results: List[ProbeResult] = []
    for m in mirrors:
        results.append(_test_one(m["name"], m["url"], test_path, timeout))
    results.sort(key=lambda x: x.score)
    return results


def speedtest_cmd(
    catalog: Dict,
    tools: List[str],
    timeout: float,
    top: int,
    project_root: Path,
) -> int:
    disabled_map = load_disabled(project_root)
    for tool in tools:
        cfg = catalog["tools"][tool]
        print(f"\n[{tool}] speed test")
        results = speedtest_tool(tool, cfg, timeout, disabled_map, include_disabled=False)
        shown = 0
        for r in results:
            if not r.ok:
                print(f"  - {r.name:14} FAIL ({r.error})")
                continue
            shown += 1
            print(
                f"  - {r.name:14} latency={r.latency_ms:7.1f}ms "
                f"download={r.download_mbps:7.2f}Mbps score={r.score:7.1f}"
            )
            if shown >= top:
                break
        fastest = next((x for x in results if x.ok), None)
        if fastest:
            print(f"  -> fastest: {fastest.name} ({fastest.url})")
        else:
            print("  -> no reachable mirror (try list-disabled / verify)")
    return 0


def _pick_mirror(
    tool: str,
    cfg: Dict,
    prefer: Optional[str],
    timeout: float,
    disabled_map: Dict[str, set],
) -> Tuple[str, str]:
    if prefer:
        for m in cfg["mirrors"]:
            if m["name"] == prefer:
                if mirror_entry_disabled(tool, m, disabled_map):
                    raise ValueError(f"Mirror '{prefer}' is disabled for {tool}.")
                return m["name"], m["url"]
        raise ValueError(f"Mirror '{prefer}' not found in catalog.")
    tested = speedtest_tool(tool, cfg, timeout, disabled_map, include_disabled=False)
    fastest = next((x for x in tested if x.ok), None)
    if not fastest:
        for m in cfg["mirrors"]:
            if not mirror_entry_disabled(tool, m, disabled_map):
                return m["name"], m["url"]
        raise RuntimeError("No mirrors available (all disabled?).")
    return fastest.name, fastest.url


def apply_cmd(
    project_root: Path,
    catalog: Dict,
    tools: List[str],
    prefer_map: Dict[str, str],
    timeout: float,
    dry_run: bool,
) -> int:
    os_name = _platform()
    disabled_map = load_disabled(project_root)
    docker_applied_user_path = False
    for tool in tools:
        cfg = catalog["tools"][tool]
        path = resolve_config_path(tool, cfg, os_name)
        if path is None:
            print(f"[{tool}] skipped: not supported on {os_name}")
            continue
        prefer = prefer_map.get(tool)
        try:
            mirror_name, mirror_url = _pick_mirror(tool, cfg, prefer, timeout, disabled_map)
        except Exception as e:
            print(f"[{tool}] skipped: {e}")
            continue
        old_content = _read_if_exists(path)
        new_content = _merge_config(cfg, old_content, mirror_url)
        if dry_run:
            print(f"[{tool}] DRY-RUN path={path} mirror={mirror_name} url={mirror_url}")
            continue
        try:
            snap = _save_backup(project_root, tool, path, old_content)
            _write_text(path, new_content)
        except OSError as e:
            print(f"[{tool}] failed: {e}")
            continue
        print(f"[{tool}] applied mirror={mirror_name} path={path} backup={snap}")
        if tool == "docker":
            try:
                path.resolve().relative_to(_home().resolve())
                docker_applied_user_path = True
            except ValueError:
                pass

    if "docker" in tools and (
        _platform() in ("macos", "windows") or docker_applied_user_path or _is_wsl()
    ):
        print("[docker] if Docker Desktop is running, restart Docker to take effect.")
    return 0


def restore_cmd(project_root: Path, tools: List[str], snapshot: Optional[str], dry_run: bool) -> int:
    snap = snapshot or _latest_snapshot(project_root)
    if not snap:
        print("No backups found.")
        return 1
    print(f"Using snapshot: {snap}")
    for tool in tools:
        data = _load_backup(project_root, snap, tool)
        if not data:
            print(f"[{tool}] skipped: no backup in snapshot")
            continue
        p = Path(data["path"])
        content = data.get("content", "")
        if dry_run:
            print(f"[{tool}] DRY-RUN restore path={p}")
            continue
        _write_text(p, content)
        print(f"[{tool}] restored path={p}")
    return 0


def list_mirrors_cmd(catalog: Dict, tool: str, project_root: Path) -> int:
    cfg = catalog["tools"][tool]
    dmap = load_disabled(project_root)
    print(f"[{tool}] mirrors:")
    for m in cfg["mirrors"]:
        suffix = ""
        if mirror_entry_disabled(tool, m, dmap):
            suffix = " (disabled)"
        print(f"  - {m['name']}: {m['url']}{suffix}")
    return 0


def list_snapshots_cmd(project_root: Path) -> int:
    root = _backup_root(project_root)
    if not root.exists():
        print("No snapshot history.")
        return 0
    latest = _latest_snapshot(project_root)
    snaps = [p.name for p in root.iterdir() if p.is_dir()]
    snaps.sort(reverse=True)
    for s in snaps:
        marker = " <- latest" if s == latest else ""
        print(f"{s}{marker}")
    return 0


def list_disabled_cmd(project_root: Path) -> int:
    d = load_disabled(project_root)
    if not d:
        print("No disabled mirrors.")
        return 0
    print("Disabled mirrors:")
    for tool in sorted(d.keys()):
        for name in sorted(d[tool]):
            print(f"  - {tool}/{name}")
    return 0


def verify_cmd(
    project_root: Path,
    catalog: Dict,
    tools: List[str],
    timeout: float,
    *,
    markdown: bool,
    update_health: bool,
    only_active: bool,
) -> int:
    disabled_map = load_disabled(project_root)
    stamp = _timestamp()
    report: Dict = {
        "generated_at": stamp,
        "platform": _platform(),
        "tools": {},
    }
    _ensure_parent(_reports_dir(project_root))
    json_path = _reports_dir(project_root) / f"verify-{stamp}.json"

    for tool in tools:
        cfg = catalog["tools"][tool]
        use_disabled = not only_active
        mirrors = yield_visible_mirrors(tool, cfg, disabled_map, include_disabled=use_disabled)
        if not mirrors:
            mirrors = list(cfg.get("mirrors", []))
        rows = []
        results_bool: Dict[str, bool] = {}
        for m in mirrors:
            r = _test_one(m["name"], m["url"], _tool_test_path(cfg), timeout)
            row = {
                "name": m["name"],
                "url": m["url"],
                "ok": r.ok,
                "latency_ms": r.latency_ms,
                "download_mbps": r.download_mbps,
                "score": r.score,
                "error": r.error,
            }
            rows.append(row)
            results_bool[m["name"]] = r.ok
        report["tools"][tool] = rows
        if update_health:
            update_health_checks(project_root, tool, results_bool)

    _write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Report written: {json_path}")

    if markdown:
        md_lines = [f"# Mirror3 verify {stamp}", "", f"Platform: {_platform()}", ""]
        for tool, rows in report["tools"].items():
            md_lines.append(f"## {tool}")
            md_lines.append("")
            md_lines.append("| name | ok | latency_ms | Mbps | error |")
            md_lines.append("|------|----|------------|------|-------|")
            for row in rows:
                err = (row.get("error") or "").replace("|", "\\|")[:80]
                md_lines.append(
                    f"| {row['name']} | {row['ok']} | {row['latency_ms']:.1f} | "
                    f"{row['download_mbps']:.2f} | {err} |"
                )
            md_lines.append("")
        md_path = _reports_dir(project_root) / f"verify-{stamp}.md"
        _write_text(md_path, "\n".join(md_lines))
        print(f"Markdown: {md_path}")

    return 0


def prune_cmd(
    project_root: Path,
    streak: int,
    dry_run: bool,
    clear_all: bool,
    enable_spec: Optional[str],
) -> int:
    if clear_all:
        if dry_run:
            print("DRY-RUN: would clear all disabled entries")
            return 0
        save_disabled(project_root, {})
        print("Cleared disabled.json")
        return 0

    if enable_spec:
        emap = parse_prefer(enable_spec)
        d = load_disabled(project_root)
        for tool, name in emap.items():
            if tool in d and name in d[tool]:
                d[tool].discard(name)
                if not d[tool]:
                    del d[tool]
        if dry_run:
            print(f"DRY-RUN: would save disabled map: {d}")
            return 0
        save_disabled(project_root, d)
        print("Updated disabled.json (enabled listed mirrors)")
        return 0

    if streak < 1:
        print("--streak must be >= 1")
        return 1

    health = load_health(project_root)
    checks = health.get("checks", {})
    d = load_disabled(project_root)
    added: List[Tuple[str, str]] = []

    for key, seq in checks.items():
        if not isinstance(seq, list) or len(seq) < streak:
            continue
        tail = seq[-streak:]
        if not all(not x for x in tail):
            continue
        if ":" not in key:
            continue
        tool, name = key.split(":", 1)
        d.setdefault(tool, set()).add(name)
        added.append((tool, name))

    if not added:
        print("No mirrors matched prune criteria (consecutive failures).")
        return 0

    uniq = sorted(set(added))
    print("Prune would disable (tool/name):")
    for tool, name in uniq:
        print(f"  - {tool}/{name}")

    if dry_run:
        return 0
    save_disabled(project_root, d)
    print(f"Disabled {len(uniq)} mirror(s); written {_disabled_path(project_root)}")
    return 0


def parse_prefer(raw: Optional[str]) -> Dict[str, str]:
    """
    --prefer accepts: tool=name,tool=name
    """
    if not raw:
        return {}
    out: Dict[str, str] = {}
    for part in [x.strip() for x in raw.split(",") if x.strip()]:
        if "=" not in part:
            raise ValueError("--prefer format: tool=mirror,tool=mirror")
        t, n = part.split("=", 1)
        t, n = t.strip(), n.strip()
        if not t or not n:
            raise ValueError("--prefer format: tool=mirror,tool=mirror")
        out[t] = n
    return out


def refresh_cmd(project_root: Path, source_url: str) -> int:
    """
    Pull latest catalog JSON from remote URL.
    """
    req = urllib.request.Request(source_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            content = resp.read().decode("utf-8")
        parsed = json.loads(content)
    except Exception as e:
        print(f"refresh failed: {e}")
        return 1
    if "tools" not in parsed:
        print("refresh failed: invalid catalog payload (missing 'tools').")
        return 1
    p = _catalog_path(project_root)
    p.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"catalog updated: {p}")
    return 0


def run_cmd(cmd: List[str]) -> Tuple[int, str]:
    try:
        res = subprocess.run(cmd, check=False, capture_output=True, text=True)
        text = (res.stdout or "").strip() or (res.stderr or "").strip()
        return res.returncode, text
    except Exception as e:
        return 1, str(e)


def doctor_cmd(catalog: Dict, tools: List[str]) -> int:
    """
    Read current tool-level settings from command output if available.
    """
    checks = {
        "npm": ["npm", "config", "get", "registry"],
        "pnpm": ["pnpm", "config", "get", "registry"],
        "yarn": ["yarn", "config", "get", "registry"],
        "pip": [sys.executable, "-m", "pip", "config", "list"],
        "uv": ["uv", "help"],
        "go": ["go", "env", "GOPROXY"],
        "cargo": ["cargo", "--version"],
        "rustup": ["rustup", "--version"],
        "bun": ["bun", "--version"],
    }
    for tool in tools:
        cmd = checks.get(tool)
        if not cmd:
            continue
        rc, out = run_cmd(cmd)
        if rc == 0:
            print(f"[{tool}] OK {out}")
        else:
            print(f"[{tool}] FAIL {out}")
    return 0


def schedule_cmd(project_root: Path, tools_arg: Optional[str], source_url: Optional[str]) -> int:
    tools = tools_arg or "npm,pnpm,yarn,pip,uv,go,cargo,rustup,bun,gradle,maven,nuget,gem,composer,docker"
    py = sys.executable
    script = project_root / "mirror3.py"
    refresh_part = f"{py} \"{script}\" refresh --source-url \"{source_url}\" && " if source_url else ""
    if _platform() == "windows":
        cmd = (
            f'{refresh_part}{py} "{script}" apply --tools {tools} --timeout 4'
            .replace(" && ", " ^&^& ")
        )
        print("Windows Task Scheduler (daily 09:00) example:")
        print(
            f'schtasks /Create /TN "Mirror3 Daily" /SC DAILY /ST 09:00 '
            f'/TR "{cmd}" /F'
        )
        return 0

    maintain = (
        f'{py} "{script}" verify --markdown && '
        f'{py} "{script}" prune --streak 3 && '
    )
    shell_cmd = f'{refresh_part}{maintain}{py} "{script}" apply --tools {tools} --timeout 4'
    print("macOS/Linux cron (daily 09:00) example:")
    print(f'0 9 * * * {shell_cmd} >> "{project_root}/.mirror3/cron.log" 2>&1')
    print("\nDaily maintenance chain: verify -> prune -> apply")
    print("\nmacOS launchd helper file location:")
    print(f'  {project_root}/templates/macos/com.mirror3.daily.plist')
    print("Windows XML template location:")
    print(f'  {project_root}/templates/windows/mirror3-daily.xml')
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mirror3",
        description="Cross-platform mirror switcher with speed test and rollback",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("list-tools", help="List supported tools")

    p_lm = sub.add_parser("list-mirrors", help="List mirrors for one tool")
    p_lm.add_argument("--tool", required=True)

    p_st = sub.add_parser("speedtest", help="Speed test mirrors")
    p_st.add_argument("--tools", help="Comma-separated tools")
    p_st.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p_st.add_argument("--top", type=int, default=3)

    p_ap = sub.add_parser("apply", help="Apply mirror config")
    p_ap.add_argument("--tools", help="Comma-separated tools")
    p_ap.add_argument(
        "--prefer",
        help="tool=mirror,tool=mirror (if absent, auto-pick fastest)",
    )
    p_ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p_ap.add_argument("--dry-run", action="store_true")

    p_rs = sub.add_parser("restore", help="Restore from backup snapshot")
    p_rs.add_argument("--tools", help="Comma-separated tools")
    p_rs.add_argument("--snapshot", help="Snapshot id, default LATEST")
    p_rs.add_argument("--dry-run", action="store_true")

    p_ls = sub.add_parser("list-snapshots", help="List backup snapshots")
    p_ls.set_defaults(_no_tools=True)

    p_status = sub.add_parser("status", help="Show current config per tool")
    p_status.add_argument("--tools", help="Comma-separated tools")

    p_doc = sub.add_parser("doctor", help="Try command-level checks")
    p_doc.add_argument("--tools", help="Comma-separated tools")

    p_rf = sub.add_parser("refresh", help="Update catalog from remote JSON URL")
    p_rf.add_argument("--source-url", required=True)

    p_sc = sub.add_parser("schedule", help="Print scheduler commands/templates")
    p_sc.add_argument("--tools", help="Comma-separated tools for daily apply")
    p_sc.add_argument("--source-url", help="Optional catalog URL for daily refresh first")
    p_sc.set_defaults(_no_tools=True)

    sub.add_parser("list-disabled", help="List mirrors disabled by prune")

    p_vf = sub.add_parser("verify", help="Probe mirrors and write health report")
    p_vf.add_argument("--tools", help="Comma-separated tools (default: all)")
    p_vf.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p_vf.add_argument("--markdown", action="store_true", help="Also write verify-*.md")
    p_vf.add_argument(
        "--no-update-health",
        action="store_true",
        help="Do not append results to .mirror3/health.json",
    )
    p_vf.add_argument(
        "--all-mirrors",
        action="store_true",
        help="Include mirrors already marked disabled",
    )

    p_pr = sub.add_parser("prune", help="Disable mirrors with consecutive verify failures")
    p_pr.add_argument(
        "--streak",
        type=int,
        default=3,
        help="Disable when last N health checks are all failures (default: 3)",
    )
    p_pr.add_argument("--dry-run", action="store_true")
    p_pr.add_argument("--clear", action="store_true", help="Clear all disabled entries")
    p_pr.add_argument(
        "--enable",
        help="Re-enable mirrors: tool=mirror,tool=mirror",
    )
    p_pr.set_defaults(_no_tools=True)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parent
    catalog = load_catalog(project_root)

    if args.command == "list-tools":
        return list_tools_cmd(catalog)

    if args.command == "list-snapshots":
        return list_snapshots_cmd(project_root)

    if args.command == "refresh":
        return refresh_cmd(project_root, args.source_url)

    if args.command == "schedule":
        return schedule_cmd(project_root, args.tools, args.source_url)

    if args.command == "list-mirrors":
        tool = args.tool
        if tool not in catalog["tools"]:
            print(f"Unknown tool: {tool}")
            return 1
        return list_mirrors_cmd(catalog, tool, project_root)

    if args.command == "list-disabled":
        return list_disabled_cmd(project_root)

    if args.command == "verify":
        tools = parse_tools(getattr(args, "tools", None), catalog)
        return verify_cmd(
            project_root,
            catalog,
            tools,
            args.timeout,
            markdown=args.markdown,
            update_health=not args.no_update_health,
            only_active=not args.all_mirrors,
        )

    if args.command == "prune":
        return prune_cmd(
            project_root,
            streak=args.streak,
            dry_run=args.dry_run,
            clear_all=args.clear,
            enable_spec=args.enable,
        )

    tools = parse_tools(getattr(args, "tools", None), catalog)

    if args.command == "speedtest":
        return speedtest_cmd(catalog, tools, args.timeout, args.top, project_root)

    if args.command == "apply":
        prefer_map = parse_prefer(args.prefer)
        return apply_cmd(
            project_root=project_root,
            catalog=catalog,
            tools=tools,
            prefer_map=prefer_map,
            timeout=args.timeout,
            dry_run=args.dry_run,
        )

    if args.command == "restore":
        return restore_cmd(
            project_root=project_root,
            tools=tools,
            snapshot=args.snapshot,
            dry_run=args.dry_run,
        )

    if args.command == "status":
        return status_cmd(project_root, catalog, tools)

    if args.command == "doctor":
        return doctor_cmd(catalog, tools)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
