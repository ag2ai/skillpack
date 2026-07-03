#!/usr/bin/env python3
"""gen-registry.py — build registry.yaml from the manifests in this repo.

The registry index is the discovery layer: skills × versions × digest × status
× compatibility, generated from the source manifests so it can never drift from
them (CI regenerates and fails on any uncommitted delta — see .github/workflows/
ci.yml). Phase-1 backend is this git repo; the same index shape serves a hosted
API later (the manifest + digest + index are the contract; the backend swaps).

Stdlib only — no PyYAML dependency, so it runs in CI with zero install. Loads
skill.json directly; for skill.yaml uses PyYAML if present else a minimal reader
covering the fields the index needs (name, version, quality.*, runtime.*).

Usage:
  python3 tools/gen-registry.py            # print the index to stdout
  python3 tools/gen-registry.py --write    # write registry.yaml
  python3 tools/gen-registry.py --check    # exit 1 if registry.yaml is stale
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path(__file__).resolve().parent, text=True,
            stderr=subprocess.DEVNULL).strip()
        if top:
            return Path(top)
    except Exception:  # noqa: BLE001
        pass
    return Path(__file__).resolve().parents[1]


REPO = _repo_root()
REGISTRY = REPO / "registry.yaml"
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


# ---- manifest loading (stdlib-only) ---------------------------------------

def _scalar(v: str):
    v = v.strip().strip('"').strip("'")
    if v in ("true", "false"):
        return v == "true"
    if v in ("null", "~", ""):
        return None
    return v


def _flow_list(v: str):
    """Parse an inline flow list `[a, "b", c]` → [str, ...]. Not a list → None."""
    v = v.strip()
    if not (v.startswith("[") and v.endswith("]")):
        return None
    inner = v[1:-1].strip()
    if not inner:
        return []
    return [_scalar(x) for x in inner.split(",")]


def _mini_yaml(text: str) -> dict:
    """Tiny YAML-subset reader: top-level scalars/flow-lists + one level of
    nested `key:` → `  key: value|[flow-list]`. Enough for registry fields."""
    root: dict = {}
    cur: dict | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" "):
            k, _, v = line.partition(":")
            key = k.strip()
            v = v.strip()
            if v == "":
                root[key] = {}
                cur = root[key]
            else:
                fl = _flow_list(v)
                root[key] = fl if fl is not None else _scalar(v)
                cur = None
        elif cur is not None and line.startswith("  "):
            k, _, v = line.strip().partition(":")
            v = v.strip()
            if v == "":
                continue
            fl = _flow_list(v)
            cur[k.strip()] = fl if fl is not None else _scalar(v)
    return root


def _load_manifest(mf: Path):
    if mf.suffix == ".json":
        return json.loads(mf.read_text())
    try:
        import yaml  # type: ignore
        return yaml.safe_load(mf.read_text())
    except Exception:  # noqa: BLE001 — PyYAML absent → minimal fallback
        return _mini_yaml(mf.read_text())


def _discover() -> list[Path]:
    out: list[Path] = []
    for base in ("skills", "examples"):
        for mf in (REPO / base).rglob("skill.*"):
            if mf.name in ("skill.yaml", "skill.json"):
                out.append(mf)
    return sorted(out)


def _semver_key(v: str):
    m = SEMVER.match(v or "")
    if not m:
        return (0, 0, 0, "~")  # unparseable sorts lowest
    maj, mnr, pat, pre = m.groups()
    # a release (no prerelease) outranks its prereleases → empty pre sorts high
    return (int(maj), int(mnr), int(pat), pre if pre else "~~~")


# ---- index build ----------------------------------------------------------

def build_index() -> dict:
    skills: dict[str, dict] = {}
    for mf in _discover():
        m = _load_manifest(mf)
        if not isinstance(m, dict):
            continue
        name = m.get("name")
        ver = m.get("version")
        if not name or not ver:
            continue
        digest = "sha256:" + hashlib.sha256(mf.read_bytes()).hexdigest()
        q = m.get("quality") or {}
        rt = m.get("runtime") or {}
        entry = {
            "digest": digest,
            "stability": q.get("stability"),
            "eval_status": q.get("eval_status"),
            "safety_review": q.get("safety_review"),
            "runtime": {
                "agent": rt.get("agent"),
                "skillspace": rt.get("skillspace"),
                "models": rt.get("models") or [],
            },
            "path": mf.parent.relative_to(REPO).as_posix(),
        }
        skills.setdefault(name, {})[ver] = entry
    index: dict = {"schema_version": 1, "skills": {}}
    for name in sorted(skills):
        versions = skills[name]
        latest = sorted(versions, key=_semver_key)[-1]
        index["skills"][name] = {"latest": latest, "versions": versions}
    return index


# ---- deterministic YAML emit (fixed shallow shape) ------------------------

def _yv(v) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    if s == "" or re.search(r"[:#\[\]{},&*!|>%@`\"']", s) or s != s.strip():
        return json.dumps(s)
    return s


def _yl(items) -> str:
    return "[" + ", ".join(_yv(x) for x in items) + "]"


def dump_yaml(index: dict) -> str:
    L = [
        "# registry.yaml — the Skill Space index. GENERATED by tools/gen-registry.py.",
        "# Do not edit by hand; CI regenerates it from manifests and fails on drift.",
        f"schema_version: {index['schema_version']}",
        "skills:",
    ]
    skills = index["skills"]
    if not skills:
        L.append("  {}")
    for name in skills:
        s = skills[name]
        L.append(f"  {_yv(name)}:")
        L.append(f"    latest: {_yv(s['latest'])}")
        L.append("    versions:")
        for ver in sorted(s["versions"], key=_semver_key):
            e = s["versions"][ver]
            L.append(f"      {_yv(ver)}:")
            L.append(f"        digest: {_yv(e['digest'])}")
            L.append(f"        stability: {_yv(e['stability'])}")
            L.append(f"        eval_status: {_yv(e['eval_status'])}")
            L.append(f"        safety_review: {_yv(e['safety_review'])}")
            L.append("        runtime:")
            L.append(f"          agent: {_yv(e['runtime']['agent'])}")
            L.append(f"          skillspace: {_yv(e['runtime']['skillspace'])}")
            L.append(f"          models: {_yl(e['runtime']['models'])}")
            L.append(f"        path: {_yv(e['path'])}")
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    text = dump_yaml(build_index())
    if "--check" in argv:
        cur = REGISTRY.read_text() if REGISTRY.exists() else ""
        if cur != text:
            sys.stderr.write(
                "registry.yaml is stale — run `python3 tools/gen-registry.py "
                "--write` and commit.\n")
            return 1
        print("registry.yaml is up to date.")
        return 0
    if "--write" in argv:
        REGISTRY.write_text(text)
        n = len(build_index()["skills"])
        print(f"wrote {REGISTRY.relative_to(REPO)} ({n} skill(s)).")
        return 0
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
