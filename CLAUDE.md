# Project Harness

This repository uses Harness Engineering to make Claude Code operate as a reliable software engineer.

## Core rules

- Read the relevant architecture and API documentation before changing code.
- Preserve existing project behavior unless the task explicitly changes it.
- Never expose, print, commit, or copy secrets.
- Never inspect or dump `.env` contents.
- Prefer mocks and local/test integrations before live or paid providers.
- Do not call production or paid APIs unless the user explicitly authorizes it.
- Before declaring a task complete, run the relevant verification.
- Never claim a test passed unless it actually ran and passed.
- Review the final diff for accidental changes.

## Definition of Done

A task is complete only when:

1. The requested behavior is implemented.
2. Relevant tests pass.
3. API contracts remain valid.
4. Security checks pass where applicable.
5. No secrets are exposed.
6. The final diff is reviewed.
7. Any skipped or failing verification is explicitly reported.

## Harness workflow

Understand -> Plan -> Change -> Test -> Security review -> Verify -> Review diff -> Report evidence.

Use the specialized agents, skills, and commands in `.claude/` when applicable.
