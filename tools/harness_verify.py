#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

required = [
    "CLAUDE.md",
    ".claude/agents/api-engineer.md",
    ".claude/agents/security-reviewer.md",
    ".claude/agents/verification-engineer.md",
    ".claude/agents/project-auditor.md",
    ".claude/skills/api-contracts/SKILL.md",
    ".claude/skills/security-review/SKILL.md",
    ".claude/skills/verification/SKILL.md",
    ".claude/commands/audit.md",
    ".claude/commands/verify.md",
    ".claude/commands/finish.md",
    "docs/HARNESS_ENGINEERING.md",
]

missing = [p for p in required if not (ROOT / p).is_file()]

if missing:
    print("Harness verification failed.")
    for item in missing:
        print("Missing:", item)
    sys.exit(1)

print("Harness verification passed.")
print("No network or provider calls were made.")
