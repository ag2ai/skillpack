#!/usr/bin/env python3
"""Tests for cli/skillpack.py — the resolver CLI. Stdlib only."""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "skillpack", Path(__file__).resolve().parent / "skillpack.py")
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

FAILS: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  ok  " if cond else "  FAIL ") + msg)
    if not cond:
        FAILS.append(msg)


# A synthetic index so tests don't depend on the live registry contents.
INDEX = {
    "schema_version": 1,
    "skills": {
        "@core/code-review": {
            "latest": "1.4.7",
            "versions": {
                "1.2.0": {"digest": "sha256:aa", "stability": "stable", "eval_status": "passing",
                          "safety_review": "verified", "runtime": {"agent": ">=0.9"}, "path": "p/1.2.0"},
                "1.4.7": {"digest": "sha256:bb", "stability": "stable", "eval_status": "passing",
                          "safety_review": "verified", "runtime": {"agent": ">=0.9"}, "path": "p/1.4.7"},
                "2.0.0": {"digest": "sha256:cc", "stability": "experimental", "eval_status": "none",
                          "safety_review": "none", "runtime": {"agent": ">=1.0"}, "path": "p/2.0.0"},
            },
        },
    },
}


def main() -> int:
    # --- satisfies() range matching ---
    s = sp.satisfies
    check(s("1.4.7", "*") and s("1.4.7", "") and s("1.4.7", "latest"), "wildcard/empty/latest match")
    check(s("1.4.7", "1.4.7") and not s("1.4.6", "1.4.7"), "exact match")
    check(s("1.4.7", "^1.2.0") and not s("2.0.0", "^1.2.0"), "caret stays within major")
    check(s("1.4.7", "~1.4.0") and not s("1.5.0", "~1.4.0"), "tilde stays within minor")
    check(s("1.4.7", ">=1.2.0") and not s("1.1.0", ">=1.2.0"), ">= comparator")
    check(s("1.4.7", "<2.0.0") and not s("2.0.0", "<2.0.0"), "< comparator")
    check(not s("0.2.0", "^0.1.0") and s("0.1.9", "^0.1.0"), "caret 0.x pins minor")

    # --- resolve() picks the highest satisfying version ---
    resolved, errors = sp.resolve(INDEX, {"skills": {"@core/code-review": "^1.2.0"}})
    check(errors == [] and resolved["@core/code-review"]["version"] == "1.4.7",
          "resolve caret → highest in-range (1.4.7, not 2.0.0)")
    check(resolved["@core/code-review"]["digest"] == "sha256:bb", "resolved digest pinned")

    # --- resolve() reports unmet ranges + unknown skills ---
    _, e1 = sp.resolve(INDEX, {"skills": {"@core/code-review": ">=3.0.0"}})
    check(any("no version satisfies" in x for x in e1), "unmet range flagged")
    _, e2 = sp.resolve(INDEX, {"skills": {"@core/nope": "*"}})
    check(any("not found" in x for x in e2), "unknown skill flagged")

    # --- install (lock-only) writes a deterministic lockfile ---
    tmp = Path(tempfile.mkdtemp(prefix="skillpack-test-"))
    (tmp / "agent.yaml").write_text('skills:\n  "@core/code-review": "^1.2.0"\n')
    rc = sp.cmd_install(INDEX, tmp / "agent.yaml", do_materialize=False)
    lock = json.loads((tmp / "skillpack.lock").read_text())
    check(rc == 0 and lock["lockfileVersion"] == 1
          and lock["skills"]["@core/code-review"]["version"] == "1.4.7",
          "install writes skillpack.lock with pinned version")

    # --- agent.yaml round-trip via add + reload ---
    ap = tmp / "agent2.yaml"
    sp.cmd_add(ap, "@core/code-review@~1.4.0")
    reloaded = sp._load_agent(ap)
    check(reloaded["skills"].get("@core/code-review") == "~1.4.0", "add → agent.yaml round-trips")

    # --- agent.json is also accepted ---
    (tmp / "agent.json").write_text(json.dumps({"skills": {"@core/code-review": "1.2.0"}}))
    r3, e3 = sp.resolve(INDEX, sp._load_agent(tmp / "agent.json"))
    check(e3 == [] and r3["@core/code-review"]["version"] == "1.2.0", "agent.json exact resolve")

    # --- materialize copies each resolved skill's dir into dest/<scope>/<name> ---
    src_root = Path(tempfile.mkdtemp(prefix="skillpack-src-"))
    (src_root / "p/1.4.7").mkdir(parents=True)
    (src_root / "p/1.4.7/skill.yaml").write_text("name: '@core/code-review'\n")
    (src_root / "p/1.4.7/SKILL.md").write_text("# Code Review\n")
    dest_root = tmp / "skillpack_modules"
    copied, warns = sp.materialize({"@core/code-review": {"version": "1.4.7", "path": "p/1.4.7"}},
                                   dest_root, src_root)
    landed = (dest_root / "core/code-review/skill.yaml").exists()
    check(copied == 1 and warns == [] and landed,
          "materialize copies skill into skillpack_modules/<scope>/<name>")
    # index-only entry (no source on disk) → warned, not fatal
    c2, w2 = sp.materialize({"@x/ghost": {"version": "1.0.0", "path": "nope/1.0.0"}},
                            dest_root, src_root)
    check(c2 == 0 and any("index-only" in x for x in w2), "missing source → warning, not crash")

    # --- overrides: a local override beats the registry for that skill ---
    proj = Path(tempfile.mkdtemp(prefix="skillpack-proj-"))
    ovdir = proj / "skills/overrides/core/code-review"
    ovdir.mkdir(parents=True)
    (ovdir / "skill.yaml").write_text('name: "@core/code-review"\nversion: "9.9.9-local"\n')
    (proj / "agent.yaml").write_text('skills:\n  "@core/code-review": "^1.2.0"\n')
    agent = sp._load_agent(proj / "agent.yaml")
    ov = sp.find_overrides(agent, proj)
    check(ov.get("@core/code-review") == ovdir, "conventional overrides/ dir discovered")
    r, e = sp.resolve(INDEX, agent, ov)
    check(e == [] and r["@core/code-review"]["source"] == "override"
          and r["@core/code-review"]["version"] == "9.9.9-local",
          "override wins over registry (source=override, local version)")

    # explicit agent.yaml `overrides:` also works and wins
    ex = proj / "explicit"
    (ex).mkdir()
    (ex / "skill.yaml").write_text('name: "@core/code-review"\nversion: "2.0.0-mine"\n')
    agent2 = {"skills": {"@core/code-review": "*"}, "overrides": {"@core/code-review": "explicit"}}
    ov2 = sp.find_overrides(agent2, proj)
    r2, _ = sp.resolve(INDEX, agent2, ov2)
    check(r2["@core/code-review"]["version"] == "2.0.0-mine", "explicit override honored")

    # registry entries carry source=registry
    r3b, _ = sp.resolve(INDEX, {"skills": {"@core/code-review": "^1.2.0"}})
    check(r3b["@core/code-review"]["source"] == "registry", "registry entry tagged source=registry")

    # --- audit: real 2-hop example chain verifies end-to-end ---
    rc = sp.cmd_audit(sp._load_index(), "@sutando/obsidian-vault", verify=True)
    check(rc == 0, "audit --verify on the example chain passes (digests chain)")

    # --- audit: a broken parent_digest fails verification ---
    idx = {"skills": {"@x/y": {"latest": "2.0.0", "versions": {
        "1.0.0": {"digest": "sha256:AAA", "path": "p/1"},
        "2.0.0": {"digest": "sha256:BBB", "path": "p/2"}}}}}
    _orig = sp._read_manifest
    sp._read_manifest = lambda d: (
        {"lineage": {"parent": "@x/y@1.0.0",
                     "evolution": {"parent_digest": "sha256:WRONG", "author": "agent:z"}}}
        if d.name == "2" else {})
    try:
        rc2 = sp.cmd_audit(idx, "@x/y", verify=True)
    finally:
        sp._read_manifest = _orig
    check(rc2 == 1, "broken parent_digest → audit --verify fails (rc 1)")

    print(f"\n{'PASS — all checks green' if not FAILS else f'FAIL — {len(FAILS)} failing'}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())
