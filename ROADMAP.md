# SkillPack — roadmap

Phased so each step is usable on its own and the format stays stable while distribution evolves.

## Phase 0 — Format (this repo, now) ✅
- `schemas/skill.v1.json` — the manifest contract. **Done.**
- Example skill(s). **Done** (`examples/code-review`).
- `tools/lint-skill.py` — stdlib validator + **permission cross-check** (declared `network` vs actual code), ported from Sutando's Phase-1 work (`sonichi/sutando` #1902). **Done.**

## Phase 1 — Git-based registry ▶️ (in progress)
- `registry.yaml` — the index (skills × versions × digest × status × compatibility), **generated from manifests** by `tools/gen-registry.py`; never hand-edited. **Done.**
- CI (`.github/workflows/ci.yml`): lint `--all --strict` + registry **drift-check** (`gen-registry.py --check` fails if the committed index is stale). **Done.**
- Skills submitted via **PR** (review + history + forks + governance for free); merge = published. Next: a `skills/<scope>/<name>/versions/<ver>/` layout convention + `skillpack diff` over the index.

## Phase 2 — CLI + lockfile ▶️ (in progress)
- `cli/skillpack.py` — the resolver. **Done (MVP):** `list` / `info` / `add` / `install` / `lint`. `install` reads `agent.yaml` (declared skills + SemVer ranges), resolves each to the highest satisfying registry version, and writes **`skillpack.lock`** (pinned version + digest) for reproducible behavior. Range support: exact / `^` / `~` / `>=/>/<=/<` / `*`. Stdlib-only; resolver tests in CI.
- `install` **materializes** resolved skills into `skillpack_modules/<scope>/<name>/` (or `--lock-only`). **Done.**
- **Precedence + overrides** — a local `skills/overrides/<scope>/<name>/` (or explicit `overrides:` in agent.yaml) beats the registry, so a `@user` edit shadows a `@core` skill without mutating it. Lockfile records `source: registry|override`. **Done.**
- **Next:** `fork` (scaffold an override from a registry skill) + the risk-aware `update`.
- `fork` / `publish` / `diff`.
- **Risk-aware `update`**: reports behavior/permission/eval/migration deltas instead of blind-bumping.
- **Lineage audit trail** (spec: `docs/lineage-audit-trail.md`) — per-version evolution entries (author/rationale/eval-delta/parent-digest) so agent **self-evolution** is replayable + accountable; `skillpack audit` walks/verifies the chain.

## Phase 3 — Hosted + federated registry
- `registry.skillpack.dev`-shaped API (search / publish / versions / owners / downloads / compatibility / verification / deprecation / fork-graph / eval results).
- Artifact layer over OCI / object store; **Sigstore/Cosign** signing + eval attestations. The CLI hides OCI from users.
- Federated private registries (`skills.company.com`).
- Natural home: **AG2 Space** as the discovery/marketplace surface.

## Non-goals / decisions to keep it lean
- Not literally npm-compatible (skills aren't Node packages).
- Flat pins + lockfile, not SAT dependency solving, until scale demands it.
- Don't force users to understand OCI — the CLI abstracts distribution.
