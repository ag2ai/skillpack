#!/usr/bin/env python3
"""lint-skill.py — validate Skill Space manifests against schemas/skill.v1.json.

Stdlib only (no jsonschema dep → runs in CI with zero install). Ported from
Sutando's Phase-1 linter and adapted for the canonical v1 format: `@scope/name`
namespaces, nested `quality`/`runtime`/`permissions`, and the permission
cross-check (declared `permissions.network` vs actual network calls in the
skill's source — a permission that lies is worse than none).

Accepts skill.yaml or skill.json (YAML parsed via a tiny stdlib-only reader if
PyYAML is absent — we only need the top-level scalar/enum fields for linting).

Usage:
  python3 tools/lint-skill.py skills/core/code-review/versions/1.4.7
  python3 tools/lint-skill.py --all
  python3 tools/lint-skill.py --all --strict
"""
from __future__ import annotations

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
SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$")
NAME_RE = re.compile(r"^@[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9-]*$")
STABILITY = {"experimental", "stable", "deprecated"}
EVAL_STATUS = {"none", "failing", "passing"}
SAFETY = {"none", "pending", "verified", "unsafe"}
FS = {"none", "read", "read-write"}
NET_SIGNALS = re.compile(
    r"\b(urllib\.request|requests\.|httpx|aiohttp|socket\.|websocket|fetch\(|curl\s|wget\s)\b")


def _load_manifest(d: Path):
    """Return the parsed manifest dict, or None. Prefers skill.json; for
    skill.yaml, uses PyYAML if present else a minimal top-level scalar reader
    (enough for the fields the linter checks)."""
    j = d / "skill.json"
    if j.exists():
        return json.loads(j.read_text())
    y = d / "skill.yaml"
    if not y.exists():
        return None
    try:
        import yaml  # type: ignore
        return yaml.safe_load(y.read_text())
    except Exception:  # noqa: BLE001 — PyYAML absent → minimal fallback
        return _mini_yaml(y.read_text())


def _mini_yaml(text: str) -> dict:
    """Tiny YAML-subset reader: top-level `key: value` scalars + one level of
    `key:`→nested `  key: value`. Only what lint checks need (name, version,
    quality.*, permissions.network, runtime.*). Lists/complex values are skipped."""
    root: dict = {}
    cur: dict | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" "):
            if line.rstrip().endswith(":") and ":" == line.strip()[-1]:
                key = line.strip()[:-1]
                root[key] = {}
                cur = root[key]
            else:
                k, _, v = line.partition(":")
                root[k.strip()] = _scalar(v.strip())
                cur = None
        elif cur is not None and line.startswith("  "):
            k, _, v = line.strip().partition(":")
            if v.strip():
                cur[k.strip()] = _scalar(v.strip())
    return root


def _scalar(v: str):
    v = v.strip().strip('"').strip("'")
    if v in ("true", "false"):
        return v == "true"
    if v in ("null", "~", ""):
        return None
    return v


def _lint(d: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    m = _load_manifest(d)
    tag = d.name
    if m is None:
        return ([f"{tag}: no skill.yaml/skill.json"], [])
    if not isinstance(m, dict):
        return ([f"{tag}: manifest top-level must be a mapping"], [])

    def err(x): errors.append(f"{tag}: {x}")
    def warn(x): warnings.append(f"{tag}: {x}")

    for req in ("name", "version"):
        if not m.get(req):
            err(f"missing required '{req}'")
    name = m.get("name")
    if isinstance(name, str) and not NAME_RE.match(name):
        err(f"name '{name}' must be @scope/name (lowercase-dash)")
    ver = m.get("version")
    if isinstance(ver, str) and not SEMVER.match(ver):
        err(f"version '{ver}' is not SemVer")

    q = m.get("quality")
    if not isinstance(q, dict) or not q.get("stability"):
        err("quality.stability is required")
    elif q.get("stability") not in STABILITY:
        err(f"quality.stability '{q.get('stability')}' invalid")
    if isinstance(q, dict):
        if q.get("eval_status") and q["eval_status"] not in EVAL_STATUS:
            err(f"quality.eval_status '{q['eval_status']}' invalid")
        if q.get("safety_review") and q["safety_review"] not in SAFETY:
            err(f"quality.safety_review '{q['safety_review']}' invalid")

    perms = m.get("permissions")
    if isinstance(perms, dict):
        if perms.get("filesystem") and perms["filesystem"] not in FS:
            err(f"permissions.filesystem '{perms['filesystem']}' invalid")
        if perms.get("network") is False:
            hit = _net_hit(d)
            if hit:
                warn(f"permissions.network=false but code references {hit[0]} (in {hit[1]})")

    return (errors, warnings)


def _net_hit(d: Path):
    for f in d.rglob("*"):
        if f.is_file() and f.suffix in (".py", ".ts", ".js", ".sh", ".cjs", ".mjs"):
            try:
                mo = NET_SIGNALS.search(f.read_text(errors="ignore"))
            except OSError:
                continue
            if mo:
                return (mo.group(1), f.relative_to(d).as_posix())
    return ()


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    args = [a for a in argv if not a.startswith("--")]
    if "--all" in argv:
        targets = sorted({p.parent for p in REPO.glob("skills/**/skill.*")
                          if p.name in ("skill.yaml", "skill.json")}
                         | {p.parent for p in REPO.glob("examples/**/skill.*")
                            if p.name in ("skill.yaml", "skill.json")})
    elif args:
        targets = [Path(a) if Path(a).is_absolute() else REPO / a for a in args]
    else:
        print("usage: lint-skill.py <skill-dir> | --all [--strict]", file=sys.stderr)
        return 2

    e_all, w_all = [], []
    for t in targets:
        e, w = _lint(t)
        e_all += e
        w_all += w
    for w in w_all:
        print(f"  ⚠ {w}")
    for e in e_all:
        print(f"  ✗ {e}")
    print(f"\nlint-skill: {len(targets)} manifest(s), {len(e_all)} error(s), {len(w_all)} warning(s)")
    return 1 if (e_all or (strict and w_all)) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
