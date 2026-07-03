# Obsidian Vault Capture

Capture notes, tasks, and thoughts into a Sutando-owned Obsidian vault at `<workspace>/obsidian-vault`.

## Behavior

- A voice/inline tool writes Markdown files directly to the vault directory on the local filesystem.
- Obsidian watches that directory, so captures appear instantly — no Obsidian plugin or API required.
- Filesystem-only: no network access, no secrets (see `permissions` in `skill.yaml`).

## Contract

- **Input:** free-text note/task content (+ optional title/tags).
- **Output:** a Markdown file created under the vault; returns the written path.
- **Guarantee:** never deletes or overwrites existing notes — capture is append/create-only.

## Provenance

Implementation lives in [sonichi/sutando `skills/obsidian-vault`](https://github.com/sonichi/sutando/tree/main/skills/obsidian-vault) (a manifest-loaded TS tool). This SkillPack entry is the published package identity + contract; the resolver points at the source for the implementation.
