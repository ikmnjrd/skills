# ikeda-agent-skills

Personal curated agent skills for GitHub Copilot / coding agents.

## Included skills

- `grill-me` — stress-test a plan or design by having the agent ask focused questions one at a time.
- `grill-with-docs` — stress-test a plan against project language and decisions, updating `CONTEXT.md` and ADRs when useful.
- `summarize-changes` — summarize code changes, impact, validation, and remaining risk. This is an original skill.
- `audit-command-permissions` — audit Codex and Claude Code logs and propose conservative allow, prompt, and deny command rules. This is an original skill.
- `apply-command-permissions` — dry-run, validate, apply, back up, and roll back selected Codex and Claude Code permission rules. This is an original skill.

## Layout

```text
skills/
  grill-me/
    SKILL.md
    VENDOR.md
  grill-with-docs/
    SKILL.md
    CONTEXT-FORMAT.md
    ADR-FORMAT.md
    VENDOR.md
  summarize-changes/
    SKILL.md
    agents/
      openai.yaml
  audit-command-permissions/
    SKILL.md
    scripts/
      audit_command_permissions.py
      permission_audit/
      tests/
  apply-command-permissions/
    SKILL.md
    scripts/
      apply_command_permissions.py
      permission_apply/
      tests/
LICENSES/
  mattpocock-skills-LICENSE
vendor/
  mattpocock-skills.lock.json
```

## Attribution

The initial skills are vendored from Matt Pocock's `mattpocock/skills` repository.

Original repository:
https://github.com/mattpocock/skills

Original author:
Matt Pocock

License:
MIT

The upstream license text is preserved at `LICENSES/mattpocock-skills-LICENSE`.

Local modifications are documented in each vendored skill's `VENDOR.md`.

## Policy

- Upstream skills are not silently rewritten.
- Local changes to vendored skills must be documented in `VENDOR.md`.
- Script-bearing skills must be reviewed before use.
- Vendored skills should be pinned by upstream commit when possible.

## Maintaining skills

Every directory under `skills/` must contain:

- `SKILL.md` with YAML frontmatter containing non-empty `name` and `description` fields.

Vendored skills must also contain `VENDOR.md` describing their origin and local changes. Original skills do not need `VENDOR.md`.

Additional documentation and resources should stay inside the skill directory. Keep skill directories small and focused.

### Adding a skill

1. Create `skills/<skill-name>/SKILL.md`.
2. Add the skill to the **Included skills** list above.
3. If the skill is vendored:
   - Add `skills/<skill-name>/VENDOR.md`.
   - Preserve the upstream attribution and license.
   - Add or reuse the upstream license file under `LICENSES/`.
   - Add an entry to the appropriate lock file under `vendor/`.
   - Pin `importedRef` to the full upstream commit SHA and record `retrievedAt`.
   - List all included upstream files in the lock entry when the skill contains more than `SKILL.md`.
4. Review executable scripts before adding them to a vendored skill.
5. Run the validation command below.

For an original skill, do not add a lock entry or `VENDOR.md`. The `summarize-changes` directory is the minimal example.

### Updating a vendored skill

1. Identify the new full upstream commit SHA.
2. Compare each vendored file with the file at that commit.
3. Apply the upstream changes without discarding intentional local adaptations.
4. Update the skill's `VENDOR.md` with the new commit, retrieval date, and an accurate summary of local changes.
5. Update the corresponding lock entry under `vendor/`.
6. Keep the existing upstream license file intact.
7. Run the validation command below and review the final diff.

### Making local changes

When changing a vendored skill without updating from upstream:

1. Make the smallest focused change possible.
2. Update the skill's `VENDOR.md` and the lock entry's `localChanges` field so they describe the change accurately.
3. Do not add executable scripts without review.
4. Run the validation command below.

### Removing a skill

1. Remove its directory under `skills/`.
2. Remove it from the **Included skills** list.
3. Remove its entry from the relevant lock file under `vendor/`.
4. Remove attribution from `NOTICE.md` only when it no longer applies to any remaining skill.
5. Remove an upstream license file only when no remaining skill uses it.
6. Run the validation command below.

### Validation

Validation requires `jq`. Run this after every addition, update, or removal:

```sh
bash scripts/validate-skills.sh
```

The validator checks that at least one skill exists, required files are present, and `SKILL.md` has the required frontmatter.

## Suggested installation into a project

Copy the required skill directories into the target repository's `.github/skills/` directory:

```sh
mkdir -p .github/skills
cp -R skills/grill-me .github/skills/grill-me
cp -R skills/grill-with-docs .github/skills/grill-with-docs
cp -R skills/summarize-changes .github/skills/summarize-changes
```

Or keep this repository as your central source and use your preferred sync script.
