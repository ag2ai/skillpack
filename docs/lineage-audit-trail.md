# Lineage audit trail — the substrate for safe self-evolution

> Status: **spec / proposal.** Defines the schema extension + the write/verify
> mechanisms. Non-breaking: all fields are optional; a skill with no evolution
> history is just a fork graph with one node.

## Why

We want agents that **self-evolve** — an agent that improves its own skills:
edits a prompt, tightens a contract, forks-and-specializes, promotes a variant.
That is only *safe* if every change is **auditable**: you must be able to
reconstruct, for any skill version, **who/what changed it, from what, why, and
verified by what**. An agent that mutates itself without an audit trail is
unaccountable — you cannot trust a self-evolving system you cannot replay.

Today's lineage answers *"what forked from what."* Self-evolution needs it to
also answer *"who/what changed this, why, and with what evidence."* This spec
adds that — the difference between a **fork graph** and a **self-evolution audit
trail**.

## Design: per-version entries, chained by digest

The audit trail is **not** a growing list inside one manifest (that bloats and
is easy to forge). Instead, each skill **version** records exactly one evolution
entry describing *how that version came to be*, plus its **parent's digest**.
Walking parent → parent (verifying each digest) reconstructs the whole chain —
git/Merkle-style, tamper-evident by construction.

```
@core/code-review@1.4.7
  lineage.parent        = @core/code-review@1.4.6
  lineage.evolution.parent_digest = sha256:<digest of 1.4.6>   # must match
  lineage.evolution.author        = agent:sutando-qingyun-001  # who/what
  lineage.evolution.policy        = auto-eval-promote-v1       # under what rule
  lineage.evolution.rationale     = "eval pass-rate 0.88→0.94; no perm change"
  lineage.evolution.eval_delta    = { before, after, suite }
  lineage.evolution.permissions_delta = none                  # widened|narrowed|none
  provenance.digest    = sha256:<digest of 1.4.7>              # this version
  provenance.signed    = true                                  # signature over the above
```

## Schema extension (`schemas/skill.v1.json`)

Additive to the existing `lineage` (`forked_from`, `upstream_intent`, `replaces`,
`variants`):

```jsonc
"lineage": {
  "forked_from": "@scope/name@version",   // origin fork (existing)
  "parent":      "@scope/name@version",   // NEW: the immediate prior version this evolved from
  "evolution": {                           // NEW: how THIS version came to be
    "author":  "string",                  // "human:<handle>" | "agent:<agent-id>"
    "policy":  "string",                  // the policy an agent acted under (agent authors only)
    "timestamp": "string",                // ISO-8601
    "rationale": "string",                // why this change was made
    "eval_delta": {                       // the evidence that justified it
      "suite":  "string",                 // eval suite id
      "before": "string",                 // metric/status at the parent
      "after":  "string"                  // metric/status at this version
    },
    "permissions_delta": "none | widened | narrowed",  // did capabilities change?
    "parent_digest": "string"             // sha256:… of the parent version — chain integrity
  }
}
```

Integrity leans on the **existing** `provenance.digest` + `provenance.signed`:
each version has its own content digest and a signature over `(manifest + code)`;
the child records the parent's digest, so a forged history breaks the chain.

## Author taxonomy — the load-bearing field for self-evolution

`evolution.author` is what turns a fork graph into a self-evolution ledger:

- `human:<handle>` — a person authored/reviewed this version.
- `agent:<agent-id>` — an agent authored it **autonomously**; `policy` records
  the rule it acted under (e.g. `auto-eval-promote-v1`), so an autonomous change
  is never anonymous. An auditor can ask "show me every version an agent authored
  without human review" and get an exact answer.

## Writing the trail — the self-maintain loop

When the self-maintain process (see `MANIFEST.md` → *Skill maturity*) evolves a
skill, it does not silently overwrite. It **cuts a new version** and writes:

1. `lineage.parent` = the version it started from; `evolution.parent_digest` =
   that version's `provenance.digest`.
2. `evolution.author` = `agent:<id>`, `evolution.policy` = the acting policy.
3. `evolution.rationale` + `evolution.eval_delta` = the decision and its evidence
   (the same signal that drove promotion — age/usage/eval).
4. `evolution.permissions_delta` — computed by diffing declared `permissions`
   against the parent (a widened capability is a hard stop / human-gated).
5. Sign the new version (`provenance.signed`).

A change that **widens permissions** or **regresses evals** is never
auto-applied — it's recorded as a *proposal* and gated on human review. That is
the safety interlock: autonomy is bounded by "no silent capability creep, no
eval regression."

## Auditing the trail — `skillpack audit`

A future CLI verb walks + verifies:

```
skillpack audit @core/code-review            # newest → origin
skillpack audit @core/code-review@1.4.7 --verify   # also check each digest/signature
```

For each hop it prints: version, author (human/agent+policy), rationale,
eval-delta, permissions-delta, and whether the parent digest + signature verify.
Output = the full "how did this skill become what it is" story, tamper-evident.

## Non-goals / phasing

- **Not** a blockchain — it's a signed Merkle-style parent chain; no consensus,
  no tokens.
- **Phase A (format):** the schema fields above + `skillpack audit` (read/verify
  from git). No signing infra required to *record* the trail — signing hardens it.
- **Phase B (self-maintain writes it):** the maturity loop authors entries.
- **Phase C (hosted):** signatures via Sigstore + audit surfaced in the registry
  UI + fork-graph visualization (ties into Phase 3 hosted registry).

## Relationship to the rest of SkillPack

This is the payoff of the fork/lineage model already in the format: `forked_from`
gave us the origin, precedence/overrides gave us safe divergence, evals gave us
evidence — the audit trail chains them so **self-evolution is replayable and
accountable**, which is the sharpest differentiator over a bundle-plus-scan
registry (a scan tells you a release is "clean"; it can't tell you *how the
agent changed itself and why*).
