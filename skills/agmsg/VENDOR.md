# Vendor metadata

Upstream: https://github.com/ikmnjrd/agmsg
Author: fujibee
Original path: repository root
Imported ref: ae155a5ad7500625970ace02d66aadfd6fb0c760
Retrieved: 2026-06-14
License: MIT

## Attribution

The messaging scripts are vendored from agmsg. The upstream license is
preserved at:

- `../../LICENSES/agmsg-LICENSE`

## Local changes

- Reworked the project into a conventional Agent Skill.
- Split common instructions from Codex and Claude Code differences.
- Store mutable state in the host skills repository's ignored `.agmsg/`.
- Added runtime-path resolution and an idempotent skill-local installer.
- Removed unsupported agent templates, plugin packaging, update, release,
  documentation, npm, and uninstall files.

## Update policy

- Review upstream script changes before importing them.
- Keep attribution and the upstream license intact.
- Reapply and test runtime-path separation after every update.
