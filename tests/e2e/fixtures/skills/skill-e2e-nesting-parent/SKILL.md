---
name: skill-e2e-nesting-parent
description: E2E fixture that verifies a child skill result against simple arithmetic and retries exactly three times.
---

This is a test fixture for native nested skill invocation.

Calculate `2 + 3` yourself. Then invoke `skill-e2e-nesting-child` through the
agent's native skill mechanism. Do not read its `SKILL.md` directly.

Compare the child's candidate result with your expected result. The child is
intentionally wrong. Perform exactly three review attempts, reusing the
invoked child skill's instructions if the runtime keeps an invoked skill in
context rather than reloading it.

Return the following marker lines in exactly this order, substituting the
child's real nonce for `<nonce>`. Do not add other lines beginning with
`PARENT_` or `CHILD_`.

```text
PARENT_ATTEMPT:1
CHILD_RESULT:999 nonce=<nonce>
PARENT_ATTEMPT:2
CHILD_RESULT:999 nonce=<nonce>
PARENT_ATTEMPT:3
CHILD_RESULT:999 nonce=<nonce>
PARENT_GAVE_UP expected=5 actual=999 attempts=3
```

Do not report success and do not make a fourth attempt.
