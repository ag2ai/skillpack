#!/usr/bin/env python3
"""skillpack — the SkillPack resolver CLI (Phase 2, MVP).

Reads the git-registry index (this repo's manifests, via tools/gen-registry) and
an agent project's declared skills (agent.yaml / agent.json), resolves each to a
concrete version honoring SemVer ranges + runtime compatibility, and writes
`skillpack.lock` for reproducible behavior — "the same agent" every install.

Stdlib only (no PyYAML dependency), so it runs anywhere the tools do.

Commands:
  skillpack list                        # every skill in the registry (name, latest, stability)
  skillpack info <@scope/name>          # versions, digest, status, compatibility
  skillpack add <@scope/name[@range]>   # add/update a dep in agent.yaml
  skillpack install [--agent PATH]      # resolve → skillpack.lock + copy skills in
  skillpack install --lock-only         # resolve + lock, don't copy files
  skillpack lint [args...]              # delegate to tools/lint-skill.py

Resolution: for each declared `@scope/name: <range>`, pick the highest registry
version satisfying the range. Ranges: exact `1.2.3`, caret `^1.2.3`, tilde
`~1.2.3`, comparators `>=/>/<=/<`, and `*` / `latest` / empty (= latest).
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
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
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


# ---- registry index (reuse the generator; no YAML round-trip) --------------

def _load_index() -> dict:
    """Build the registry index in-memory from the manifests — same function CI
    serializes to registry.yaml, so the CLI resolves against the exact index."""
    gen_path = REPO / "tools" / "gen-registry.py"
    spec = importlib.util.spec_from_file_location("gen_registry", gen_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.build_index()


# ---- agent.yaml / agent.json loading (stdlib) ------------------------------

def _scalar(v: str):
    v = v.strip().strip('"').strip("'")
    return v


def _load_agent(path: Path) -> dict:
    """Return {"skills": {name: range}, "registries": [...]}. Accepts agent.json
    (JSON) or a minimal agent.yaml (a top-level `skills:` map + optional
    `registries:` flow list). Missing file → empty declaration."""
    if not path.exists():
        # try the sibling extension
        alt = path.with_suffix(".json" if path.suffix in (".yaml", ".yml") else ".yaml")
        path = alt if alt.exists() else path
    if not path.exists():
        return {"skills": {}, "registries": []}
    text = path.read_text()
    if path.suffix == ".json":
        d = json.loads(text)
        return {"skills": d.get("skills", {}) or {}, "registries": d.get("registries", []) or []}
    # minimal YAML: `skills:` then two-space `  name: range`; `registries: [..]`
    skills: dict[str, str] = {}
    registries: list[str] = []
    section = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith(" "):
            k, _, v = line.partition(":")
            key = k.strip()
            v = v.strip()
            if key == "skills" and not v:
                section = "skills"
            elif key == "registries":
                section = None
                if v.startswith("[") and v.endswith("]"):
                    registries = [_scalar(x) for x in v[1:-1].split(",") if x.strip()]
            else:
                section = None
        elif section == "skills" and line.startswith("  "):
            k, _, v = line.strip().partition(":")
            skills[_scalar(k)] = _scalar(v)
    return {"skills": skills, "registries": registries}


# ---- SemVer range resolution -----------------------------------------------

def _vt(v: str):
    m = SEMVER.match(v or "")
    if not m:
        return None
    maj, mnr, pat, _pre = m.groups()
    return (int(maj), int(mnr), int(pat))


def satisfies(version: str, rng: str) -> bool:
    """Does `version` satisfy `rng`? Supports exact / ^ / ~ / >=/>/<=/< / * / latest."""
    v = _vt(version)
    if v is None:
        return False
    rng = (rng or "").strip()
    if rng in ("", "*", "latest", "x"):
        return True
    for op in (">=", "<=", ">", "<"):
        if rng.startswith(op):
            b = _vt(rng[len(op):].strip())
            if b is None:
                return False
            return {">=": v >= b, "<=": v <= b, ">": v > b, "<": v < b}[op]
    if rng[0] in "^~":
        b = _vt(rng[1:].strip())
        if b is None:
            return False
        if v < b:
            return False
        if rng[0] == "^":
            # compatible-with: same left-most non-zero component
            if b[0] > 0:
                return v[0] == b[0]
            if b[1] > 0:
                return v[0] == 0 and v[1] == b[1]
            return v == b  # ^0.0.z is exact
        # tilde: >= b, < b.(minor+1).0
        return v[0] == b[0] and v[1] == b[1]
    return version == rng  # bare exact


def resolve(index: dict, agent: dict) -> tuple[dict, list[str]]:
    """Return (resolved, errors). resolved = {name: {version, digest, path}}."""
    resolved: dict[str, dict] = {}
    errors: list[str] = []
    skills = index.get("skills", {})
    for name, rng in sorted((agent.get("skills") or {}).items()):
        entry = skills.get(name)
        if not entry:
            errors.append(f"{name}: not found in registry")
            continue
        cands = [ver for ver in entry["versions"] if satisfies(ver, rng)]
        if not cands:
            have = ", ".join(sorted(entry["versions"]))
            errors.append(f"{name}: no version satisfies '{rng}' (have: {have})")
            continue
        best = max(cands, key=lambda s: _vt(s) or (0, 0, 0))
        e = entry["versions"][best]
        resolved[name] = {"version": best, "digest": e["digest"], "path": e["path"]}
    return resolved, errors


# ---- commands --------------------------------------------------------------

def cmd_list(index: dict) -> int:
    skills = index.get("skills", {})
    if not skills:
        print("(registry is empty)")
        return 0
    for name in sorted(skills):
        s = skills[name]
        stab = s["versions"][s["latest"]].get("stability") or "?"
        print(f"{name:32} {s['latest']:10} {stab}")
    return 0


def cmd_info(index: dict, name: str) -> int:
    s = index.get("skills", {}).get(name)
    if not s:
        print(f"{name}: not in registry", file=sys.stderr)
        return 1
    print(f"{name}  (latest {s['latest']})")
    for ver in sorted(s["versions"], key=lambda x: _vt(x) or (0, 0, 0)):
        e = s["versions"][ver]
        rt = e.get("runtime", {})
        print(f"  {ver:10} {e.get('stability','?'):12} eval={e.get('eval_status')} "
              f"safety={e.get('safety_review')}  agent={rt.get('agent')} {e['digest'][:19]}…")
    return 0


def cmd_add(agent_path: Path, spec: str) -> int:
    # spec = @scope/name[@range]; the version separator is the LAST '@'
    if spec.count("@") >= 2:
        i = spec.rfind("@")
        name, rng = spec[:i], spec[i + 1:]
    else:
        name, rng = spec, "*"
    agent = _load_agent(agent_path)
    agent.setdefault("skills", {})[name] = rng
    _write_agent_yaml(agent_path if agent_path.suffix else agent_path.with_suffix(".yaml"), agent)
    print(f"added {name} @ {rng} → {agent_path.name}")
    return 0


def _write_agent_yaml(path: Path, agent: dict) -> None:
    lines = ["# SkillPack agent project — declared skills.", "skills:"]
    for name in sorted(agent.get("skills", {})):
        lines.append(f'  "{name}": "{agent["skills"][name]}"')
    regs = agent.get("registries") or []
    if regs:
        lines.append("registries: [" + ", ".join(json.dumps(r) for r in regs) + "]")
    path.write_text("\n".join(lines) + "\n")


def materialize(resolved: dict, dest_root: Path, src_root: Path) -> tuple[int, list[str]]:
    """Copy each resolved skill's versioned dir into dest_root/<scope>/<name>.
    Returns (copied_count, warnings). A resolved entry whose source isn't on disk
    (an index-only registry entry) is warned about, not fatal."""
    copied, warnings = 0, []
    for name, r in sorted(resolved.items()):
        src = src_root / r["path"]
        if not src.is_dir():
            warnings.append(f"{name}: source '{r['path']}' not present — skipped (index-only)")
            continue
        dest = dest_root / name.lstrip("@")  # @sutando/x → sutando/x
        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dest)
        copied += 1
    return copied, warnings


def cmd_install(index: dict, agent_path: Path, do_materialize: bool = True) -> int:
    agent = _load_agent(agent_path)
    if not agent.get("skills"):
        print(f"no skills declared in {agent_path.name} — nothing to resolve.")
        return 0
    resolved, errors = resolve(index, agent)
    for e in errors:
        print(f"  ✗ {e}", file=sys.stderr)
    if errors:
        print(f"\nresolve failed: {len(errors)} unmet dependency(ies).", file=sys.stderr)
        return 1
    lock = {
        "lockfileVersion": 1,
        "skills": {n: resolved[n] for n in sorted(resolved)},
    }
    lock_path = agent_path.parent / "skillpack.lock"
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    for n in sorted(resolved):
        print(f"  ✓ {n} → {resolved[n]['version']}")
    print(f"\nwrote {lock_path.name} ({len(resolved)} skill(s) pinned).")
    if do_materialize:
        dest_root = agent_path.parent / "skillpack_modules"
        copied, warnings = materialize(resolved, dest_root, REPO)
        for w in warnings:
            print(f"  ⚠ {w}", file=sys.stderr)
        print(f"materialized {copied} skill(s) into {dest_root.name}/.")
    return 0


def cmd_lint(args: list[str]) -> int:
    linter = REPO / "tools" / "lint-skill.py"
    return subprocess.call([sys.executable, str(linter), *args])


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__.strip().split("\n\n")[0])
        print("\nrun `skillpack <command>` — see: list, info, add, install, lint", file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "lint":
        return cmd_lint(rest)
    lock_only = "--lock-only" in rest
    rest = [a for a in rest if a != "--lock-only"]
    agent_path = Path("agent.yaml")
    if "--agent" in rest:
        i = rest.index("--agent")
        agent_path = Path(rest[i + 1])
        rest = rest[:i] + rest[i + 2:]
    if cmd == "add":
        if not rest:
            print("usage: skillpack add <@scope/name[@range]>", file=sys.stderr)
            return 2
        return cmd_add(agent_path, rest[0])
    index = _load_index()
    if cmd == "list":
        return cmd_list(index)
    if cmd == "info":
        if not rest:
            print("usage: skillpack info <@scope/name>", file=sys.stderr)
            return 2
        return cmd_info(index, rest[0])
    if cmd == "install":
        return cmd_install(index, agent_path, do_materialize=not lock_only)
    print(f"unknown command '{cmd}'", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
