# Skill Mesh — roadmap

Phased so each step is usable on its own and the format stays stable while distribution evolves.

## Phase 0 — Format (this repo, now)
- `schemas/skill.v1.json` — the manifest contract.
- `registry.yaml` index format spec.
- Example skill(s).
- Seeded by Sutando's Phase-1 work (`sonichi/sutando` #1902): manifest schema + a stdlib `lint-skill` with a **permission cross-check** (declared `network` vs actual code). That lints/validator ports here.

## Phase 1 — Git-based registry
- `registry.yaml` generated from manifests by CI; skills submitted via PR (review + history + forks + governance for free).
- `skillmesh lint` / `diff` over the index.

## Phase 2 — CLI + lockfile
- `skillmesh add / install / update / diff / fork / publish`.
- `agent.yaml` (declared skills + registries + overrides) → `skillmesh.lock` (resolved versions + digests) for reproducible agent behavior.
- Precedence: `@user > @company > @community > @core`.
- **Risk-aware `update`**: reports behavior/permission/eval/migration deltas instead of blind-bumping.

## Phase 3 — Hosted + federated registry
- `registry.skillmesh.dev`-shaped API (search / publish / versions / owners / downloads / compatibility / verification / deprecation / fork-graph / eval results).
- Artifact layer over OCI / object store; **Sigstore/Cosign** signing + eval attestations. The CLI hides OCI from users.
- Federated private registries (`skills.company.com`).
- Natural home: **AG2 Space** as the discovery/marketplace surface.

## Non-goals / decisions to keep it lean
- Not literally npm-compatible (skills aren't Node packages).
- Flat pins + lockfile, not SAT dependency solving, until scale demands it.
- Don't force users to understand OCI — the CLI abstracts distribution.
