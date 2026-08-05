---
name: security-review
description: Use when touching authentication, authorization, secrets, external APIs, database or file access, logging, or error handling. Enforces no secret exposure, least privilege, and treating external input as untrusted.
---

# Security Review Skill

Use this skill for authentication, authorization, secrets, external APIs, database access, file access, logging, and error handling.

## Rules

- Never print secret values.
- Never commit secrets.
- Never place secrets in Markdown documentation.
- Avoid returning sensitive internal errors to clients.
- Treat external input as untrusted.
- Review authorization, not only authentication.
- Prefer least privilege.
