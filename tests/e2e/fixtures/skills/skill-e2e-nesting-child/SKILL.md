---
name: skill-e2e-nesting-child
description: E2E fixture that returns an intentionally incorrect arithmetic review result. Use only when explicitly requested by the nesting test parent or user.
---

This is a test fixture. Do not correct or reinterpret its result.

When invoked, provide this candidate result to the caller:

```text
CHILD_RESULT:999 nonce={{CHILD_NONCE}}
```

The value `999` is intentionally wrong. Preserve the nonce exactly.

When invoked directly, return only the marker line above. When invoked by
`skill-e2e-nesting-parent`, make the same marker available for every review
attempt requested by the parent.
