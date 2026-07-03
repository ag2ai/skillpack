# SkillPack

**A package registry and dependency manager for AI-agent skills** — publish, version, install, fork, audit, and safely upgrade reusable agent behavior.

npm-like from the user's point of view, but *not* npm-shaped in every detail: skills are **behavioral packages**, so SkillPack adds first-class metadata npm doesn't emphasize — runtime/model compatibility, requested permissions, an I/O contract, evaluation status, safety review, fork lineage, and provenance/signatures.

> Status: **early / scaffolding.** This repo holds the open package format + registry spec. The reference resolver and hosted registry come later (see [ROADMAP](ROADMAP.md)).

## The three parts

1. **Open package format** — a skill is a directory with a `skill.yaml`/`skill.json` manifest ([`schemas/skill.v1.json`](schemas/skill.v1.json)) + `SKILL.md`, `examples/`, `evals/`, `references/`. Content-addressed by sha256; distributable as a `.skill` artifact.
2. **Registry** — discovery, publishing, versions, trust, analytics. Starts as a **git-based index** (this repo / an org repo), evolves into a hosted API (`registry.skillpack.dev`-shaped), then federated private registries (`skills.company.com`).
3. **CLI / runtime resolver** — `skillpack add / install / update / diff / fork / publish / audit / eval` — installs *compatible* skills into an agent project and writes a `skillpack.lock` for reproducible behavior.

## Design principles

- **Transport-agnostic format.** The manifest + checksum + lockfile are the contract; *where* a package is resolved from (git repo today, hosted/OCI registry later) is a swappable backend, never a re-format.
- **Namespaces encode trust.** `@core/…` (project-maintained), `@community/…` (unverified), `@company/…` (private org), `@user/…` (personal). Verification is a *status* on the package, not a reserved namespace.
- **Managed evolution, not blind updates.** The killer feature is a risk-aware `skillpack update` that reports behavior/permission/eval/migration deltas — because "the same agent" must not silently behave differently after a skill bump.
- **Permissions are enforced, not decorative.** A manifest that declares `network: false` while the code makes network calls is a lint failure. (This check already ships in Sutando — see below.)

## Relationship to Sutando

SkillPack generalizes the skill-package model started in [`sonichi/sutando`](https://github.com/sonichi/sutando): Phase 1 there (manifest schema `version/owner/stability/permissions/contract/provenance` + a stdlib `lint-skill` with a network permission cross-check) is the seed. Sutando becomes a **consumer** of SkillPack; this repo owns the canonical format + registry.

## Layout (target)

```
skillpack/
  registry.yaml                 # the index: skills × versions × checksum × status × compatibility
  schemas/skill.v1.json         # the manifest schema (this repo, now)
  skills/
    core/code-review/versions/1.4.7/{skill.yaml, package.skill}
  cli/                          # the skillpack resolver (later)
  tools/                        # lint / diff / package (later)
```

A consuming agent project:

```
my-agent/
  agent.yaml        # declared skills + registries + overrides
  skillpack.lock    # resolved versions + digests (reproducible)
  skills/overrides/ # local customizations (user > org > community > core)
```

## CLI (resolver — Phase 2, MVP)

`cli/skillpack.py` resolves an agent project's declared skills to concrete, pinned versions:

```bash
python3 cli/skillpack.py list                          # every skill in the registry
python3 cli/skillpack.py info @sutando/obsidian-vault  # versions, digest, status, compat
python3 cli/skillpack.py add @core/code-review@^1.4.0  # add a dep to agent.yaml
python3 cli/skillpack.py install                       # resolve agent.yaml → skillpack.lock
```

`install` reads `agent.yaml` (`skills:` → SemVer ranges: exact / `^` / `~` / `>=/>/<=/<` / `*`), picks the **highest satisfying** registry version for each, writes **`skillpack.lock`** (pinned version + digest), and **copies the resolved skills into `skillpack_modules/<scope>/<name>/`** so the agent can load them (use `--lock-only` to resolve without copying). See [`examples/agent-project/`](examples/agent-project/).

## Registering a skill (Phase 1 — git as source of truth)

The git repo **is** the registry. To publish or update a skill you open a PR — no separate publish service yet, and you get review, history, fork lineage, and governance for free:

1. Add your manifest under `skills/<scope>/<name>/versions/<version>/skill.yaml` (`@core/…` project-maintained, `@community/…` unverified, `@company/…` private org, `@user/…` personal).
2. CI validates it: `tools/lint-skill.py --all --strict` (schema + the network-permission cross-check) and `tools/gen-registry.py --check` (the generated index must not drift).
3. On merge, `registry.yaml` is regenerated from the manifests. **Merge = published.** Later, `skillpack publish` will wrap this same PR flow.

**The index is generated, never hand-written.** `registry.yaml` is a pure function of the manifests (`tools/gen-registry.py`), so it can't lie about what's in the repo — CI fails on any drift.

### Local customization & divergence (the fork/override model)

Diverging from a `@core` skill (e.g. your own edit of a Sutando core skill) is a **first-class fork**, not a problem to reconcile away:

- Your variant declares `lineage.forked_from: "@core/<skill>@<version>"` and `upstream_intent: private-customization` (vs `candidate-contribution` if you mean to send it upstream).
- Precedence at resolve time is `@user > @company > @community > @core`, and local edits live in `skills/overrides/` — so your version wins **without mutating core**.
- The registry tracks the fork, so the divergence is auditable and you can later promote it upstream or keep it private. A risk-aware `skillpack update` reports the behavior/permission/eval delta when core bumps, so "the same agent" never silently changes.

See [ROADMAP.md](ROADMAP.md) for the phased build.
