---
name: api-contracts
description: Use whenever an API endpoint, request/response schema, authentication or authorization flow, or external integration is added or changed. Enforces contract stability, consumer-impact review, validation, and test coverage before shipping the change.
---

# API Contracts Skill

Use this skill whenever an API endpoint, schema, authentication flow, or external integration changes.

## Procedure

1. Locate the existing endpoint and schema.
2. Identify consumers.
3. Check validation and error behavior.
4. Check authentication/authorization.
5. Update or add tests.
6. Verify backwards compatibility.
7. Document intentional contract changes.

Never invent an API contract when an existing contract can be inspected.
