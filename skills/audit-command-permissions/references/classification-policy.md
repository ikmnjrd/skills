# Classification Policy

Use this precedence:

1. `forbid`
2. `require-approval`
3. `auto-approve`

A higher-precedence risk overrides frequency, successful execution, and past
approval.

## Auto-Approve

Require all of the following:

- The command shape is understood and narrowly matchable.
- Its expected effect is read-only or limited to disposable local build/test
  output inside the working tree.
- Arguments cannot freely select arbitrary paths, hosts, repositories, code,
  scripts, or subcommands.
- It does not cross a privilege, identity, network, or trust boundary.
- It does not expose secrets or read broadly from sensitive locations.
- Its semantics and bounded effects are safe independently of whether past
  invocations were approved or successful.
- A useful `not_match` boundary can be stated.

Typical candidates, subject to flags and local behavior:

- Exact project test, lint, format-check, and build commands.
- Read-only version, status, metadata, and help commands.
- Narrow package-manager commands that do not install, publish, execute
  lifecycle scripts, or mutate lockfiles.

Do not auto-approve an executable merely because one observed invocation was
safe.

## Forbid

Recommend `forbid` when the command shape has no acceptable agent-run use in the
user's stated workflow, or when prompting is not an adequate control.

Strong indicators:

- Recursive or broad deletion outside a disposable, bounded directory.
- Filesystem, disk, database, cluster, or account destruction.
- Credential extraction, secret-store access, or attempts to disable security
  controls.
- Unrecoverable or policy-prohibited remote changes.
- Unconstrained force pushes or destructive history rewrites to protected
  branches.
- Persistence, privilege escalation, ownership changes, or broad permission
  weakening.
- Exfiltration of local files, environment data, tokens, or private keys.
- Commands explicitly identified by the user as never acceptable.

Prefer blocking the dangerous shape rather than an entire useful executable.
For example, distinguish destructive `git push` flags from read-only `git`
operations.

## Require Approval

Use this class by default. Keep approval for:

- Network writes, publishing, pushing, merging, deployment, and cloud changes.
- Dependency installation or update.
- File deletion, overwrite, movement across boundaries, or bulk mutation.
- Database migrations and stateful infrastructure operations.
- Commands using `sudo`, shells, interpreters, inline code, `eval`, or opaque
  scripts.
- Commands with substitutions, dynamic variables, unbounded globs,
  redirections, or ambiguous parsing.
- Commands whose safety depends on current branch, environment, credentials,
  target path, host, namespace, or production status.
- Rare commands or commands without enough outcome/decision evidence.

For each candidate, state the approval question concretely, such as:

- Is the destination repository and branch correct?
- Is the target inside the disposable build directory?
- Is this a development rather than production environment?
- Are the dependency and lifecycle scripts trusted?

## Evidence and Confidence

Use:

- `high`: Clear semantics, narrow pattern, multiple consistent observations,
  and no conflicting evidence.
- `medium`: Clear semantics but limited observations or meaningful contextual
  dependence.
- `low`: Incomplete records, ambiguous parsing, missing approval decisions, or
  inferred behavior.

Frequency and approval history describe usage patterns only. They may justify
prioritizing a candidate for review, but they do not improve safety confidence.

## Pattern Review

For each proposed allow pattern, construct:

- At least one observed `match`.
- At least two `not_match` examples covering a dangerous flag, target, or
  subcommand.

Downgrade to `require-approval` if the available rule language cannot express
the intended boundary reliably.
