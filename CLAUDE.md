# Familiar: Claude Code

@AGENTS.md

`AGENTS.md`, included above, is the one current repository guide (ADR-0175): architecture, commands,
guardrails and the ADR rules. **Change it there, not here.** This file holds only what is specific to
Claude Code, and `scripts/check_docs.py` fails if it starts copying the shared guide again.

## Claude Code specifics

- How the ADRs were sequenced, what each set shipped and the traps building them found is in
  `docs/ADR-HISTORY.md`, kept verbatim from when it lived here. Read the ADR and its Implementation
  block before relying on it.
- Commit, push, merge and comment only when the person you are working with asks. Work in a git
  worktree rather than `git stash`: several sessions may share one checkout.
- Deploying to the NAS (`make deploy-dev`) changes a server people listen on; ask first.
