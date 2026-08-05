# Harness Engineering

Harness Engineering is the set of project instructions, tools, agents, skills, tests, and verification gates that surround an AI coding agent.

## Purpose

The goal is not to make Claude write more code. The goal is to make Claude work safely and predictably on the whole repository.

## Model

Understand
-> Plan
-> Change
-> Test
-> Security Review
-> Verify
-> Diff Review
-> Evidence

## API safety

Use:

Mock/local test
-> Integration test
-> Live provider only with explicit authorization

Never expose provider keys.

## Why this exists

Without a harness, an agent can make a plausible code change and stop.

With a harness, the agent is expected to provide evidence that the change works and respects project constraints.

## Existing project configuration

If the repository already contains Claude Code agents, skills, rules, or documentation, merge this Harness with them rather than replacing them.
