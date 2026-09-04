# Testing Matrix

Testing Matrix turns a skill, agent, or prompt-driven workflow into realistic behavioral test prompts with explicit routing, pass criteria, and guided result tracking.

## What it tests

- Positive and natural-language activation.
- Nearby requests that should not trigger the target.
- Main-path behavior and promised outputs.
- Missing or ambiguous inputs.
- Dependency failures and safe recovery.
- Authorization, privacy, and destructive-action boundaries.
- Stateful follow-ups, reruns, and regressions.

Tests target observable behavior rather than preferred wording.

## Modes

- **Matrix only:** produce the test plan without running it.
- **Guided run:** walk through one prompt at a time and record results.
- **Results review:** evaluate responses or artifacts supplied by the user.
- **Regression update:** revise coverage after the target changes.
- **Repair and retest:** diagnose failures; target edits still require separate authorization.

For a general “help me test this” request, the skill defaults to a guided standard run.

## Installation

Install the entire `testing-matrix` directory through your normal Codex skill or plugin workflow. Keep `SKILL.md` and `agents/` together.

## Example prompts

```text
Use $testing-matrix to create a standard behavioral test matrix for this skill and guide me through it one prompt at a time.
```

```text
Create release-level regression coverage for this agent, including dependency failures and permission boundaries.
```

```text
Review these target-session responses against the attached test matrix and mark each row pass, fail, blocked, or inconclusive.
```

## How guided testing works

The matrix tells the user where each test belongs:

- a fresh target session for independent activation and boundary checks;
- the same target session for deliberate stateful sequences;
- an isolated workspace for scripts and file behavior;
- the target application for product-specific behavior;
- the current conversation for planning and result review.

Expected outcomes remain outside the copy-paste test prompt so the system under test is not coached.

## Result states

Rows are recorded as **Pass**, **Fail**, **Blocked**, or **Inconclusive**. Missing runtime access remains blocked; untested behavior is never converted into a pass.

## License

No license has been assigned by this package. Add one before public redistribution.
