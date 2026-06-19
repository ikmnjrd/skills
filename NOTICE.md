# Notices

This repository contains locally curated agent skills.

The initial skills under `skills/grill-me` and `skills/grill-with-docs` are vendored from:

- Repository: https://github.com/mattpocock/skills
- Author: Matt Pocock
- License: MIT

The original copyright and MIT license text are preserved under:

- `LICENSES/mattpocock-skills-LICENSE`

Local modifications, if any, are documented in each skill's `VENDOR.md`.

These vendored skills are included to make them easier to install, pin, review, and adapt for a GitHub-based agent workflow. They are not presented as original work.

The skills under `skills/empirical-prompt-tuning` and
`skills/extract-glossary` are vendored from:

- Repository: https://github.com/mizchi/skills
- Author: mizchi (Kotaro Chikuba)
- Original paths:
  - `meta/empirical-prompt-tuning`
  - `meta/extract-glossary`
- License: MIT, according to the upstream README default for skills without an explicit license

The upstream repository does not provide a root license file or a
skill-specific license file for this skill at the imported ref. The upstream
license declaration is recorded in:

- `LICENSES/mizchi-skills-LICENSE-NOTICE`

The upstream skill files are preserved without local content changes.

The messaging scripts under `skills/agmsg` are vendored from:

- Repository: https://github.com/ikmnjrd/agmsg
- Author: fujibee
- License: MIT

The original copyright and MIT license text are preserved under:

- `LICENSES/agmsg-LICENSE`

This repository adapts agmsg into a conventional Agent Skill and stores
mutable runtime state outside the vendored skill directory. Local changes are
documented in `skills/agmsg/VENDOR.md`.

The skill under `skills/japanese-tech-writing` is vendored from:

- Source: https://gist.github.com/k16shikano/fd287c3133457c4fd8f5601d34aa817d
- Author: k16shikano
- Original path: `SKILL.md`
- License: no explicit license found in the gist at retrieval time

The missing explicit license declaration is recorded in:

- `LICENSES/k16shikano-japanese-tech-writing-LICENSE-NOTICE`

The upstream skill file is preserved without local content changes.
