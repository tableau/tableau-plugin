---
name: codex-skill-creator
description: Create or revise a Codex skill when the user wants an installable SKILL.md, supporting references, scripts, assets, or invocation metadata. Use for skill authoring and maintenance; do not use merely to execute, troubleshoot, or grade an existing skill.
---

# Codex Skill Creator (v2.0)

Create skills that add useful, non-obvious guidance while preserving the user's scope and the runtime's authorization boundaries. Treat the active platform instructions and bundled skill validator as authoritative; this skill does not invent a separate “Codex skill” format.

## Core principles

- Assume Codex is already capable. Include only instructions, references, or helpers that materially improve decisions or reliability.
- Preserve user intent. A skill must not expand a request into unrelated writes, publishing, messaging, installation, or account changes.
- Match prescription to risk. Use fixed procedures for fragile or safety-critical operations; leave room for judgment in open-ended work.
- Keep discovery precise. The frontmatter description should identify the capability and a meaningful boundary without keyword stuffing.
- Prefer progressive disclosure. Keep shared decisions in `SKILL.md`; move conditional detail into focused `references/`, reusable deterministic logic into `scripts/`, and output ingredients into `assets/`.
- Do not require rule IDs, exit-code taxonomies, schemas, bulk mode, caches, tables of contents, or runnable snippets unless they genuinely help that skill.
- Never require a `codex-` prefix. Skill names use lowercase letters, digits, and hyphens, stay under 64 characters, and should describe the capability.

## Required structure

Every skill is a folder with a `SKILL.md` containing YAML frontmatter:

```text
skill-name/
├── SKILL.md
├── agents/openai.yaml      # optional UI metadata and invocation policy
├── scripts/                # optional executable helpers
├── references/             # optional conditional guidance
└── assets/                 # optional output ingredients
```

Minimum frontmatter:

```yaml
---
name: skill-name
description: Create or edit the relevant artifact when domain-specific handling is required.
---
```

Preserve supported existing metadata. Do not add UI fields or change implicit-invocation policy unless the user requests it or an existing policy must be retained.

## Workflow

### 1. Resolve the target

- Determine whether this is a new skill or an edit.
- Respect an explicit target location. Otherwise use the runtime's standard user-skill location.
- When editing, read the complete existing `SKILL.md` before changing anything. Inspect only supporting files needed for the requested change.
- Check for repository or workspace instructions and preserve unrelated user changes.

Ask a focused question only when an unresolved choice would materially change capability, trigger behavior, installation location, or invocation policy.

### 2. Define capability and boundaries

Write down, internally or in a short plan when useful:

- the requests the skill should handle;
- closely related requests it should not handle;
- non-obvious constraints that change Codex's behavior;
- resources or scripts that are truly reusable;
- actions requiring separate authorization at execution time.

Do not convert one historical failure, personal preference, or example into a universal rule without evidence that it is a stable invariant.

### 3. Choose the smallest useful package

- Keep a simple skill self-contained.
- Add a reference only when its content is conditional or large enough to distract from the main workflow.
- Add a script when repeated logic benefits from deterministic execution. A code block labeled runnable must actually run, but ordinary skills do not need code blocks.
- Add assets only when they belong in generated output.
- Avoid placeholder directories, duplicate documentation, changelogs, self-grades, and fictional dependencies.

For a new skill, use the initializer bundled with the active skill-creation environment when available. Do not hardcode its filesystem location. Do not initialize an existing skill again.

### 4. Write or edit safely

- Use `apply_patch` or the environment's supported editor for local changes.
- Preserve the existing skill name, invocation policy, dependencies, and unrelated resources unless the request requires a change.
- Do not delete an existing skill or supporting resource merely because it is unused by the current request; inspect callers first.
- Do not make the executing skill rewrite its own instructions during ordinary use. Proposed future rules belong in review output until the user requests a versioned skill update.
- Do not write project memory, install the skill, publish externally, or mutate a registry unless the user requested that action.

### 5. Validate observable behavior

Run the validator bundled with the active skill-creation environment against the skill folder. The structural validator is necessary but not sufficient.

Also check:

- frontmatter name matches the folder and the description is discriminating;
- every referenced local file exists and is discoverable from the relevant instruction;
- commands and tool names exist in the target runtime or have an explicit fallback;
- embedded executable blocks pass syntax checks;
- changed scripts have meaningful behavior tests, including failure paths;
- destructive or external actions require appropriate authority and have bounded recovery behavior;
- examples are clearly labeled when schematic rather than runnable.

For a complex or high-risk skill, perform an isolated forward test with a realistic request when delegation is available and authorized. Do not contaminate the working tree or touch live systems merely to test a skill.

### 6. Persist and report

- Preserve the identity of an existing persistent file when writing it back; create a new item only when the user asked for a copy or no prior identity exists.
- If the skill is maintained in a Git repository, sync requested persistent changes through that repository's normal workflow.
- Report what changed, what was validated, and any remaining limitation. Provide links to the resulting files.
- Do not claim installation, publication, or behavioral correctness beyond the checks actually performed.

## Editing guidance

When revising an existing skill, prioritize demonstrated problems:

| Symptom | Likely repair |
| --- | --- |
| Skill rarely triggers | Make the description capability-focused and discriminating |
| Skill triggers too broadly | Add one meaningful boundary; remove catchall phrasing |
| Entry point is bloated | Move conditional detail into routed references |
| Instructions conflict | Establish one authoritative rule and remove duplicates |
| Runnable example fails | Repair it and add a failure-path test, or label it schematic |
| Tool/path is unavailable | Discover the runtime capability or define a clean fallback |
| Reruns duplicate work | Check actual target state or use a complete input fingerprint |
| External mutation is implicit | Require authorization immediately before the action |
| Update overwrites user work | Preserve identity and unrelated changes; use conflict guards |

Prefer a narrow correction over adding more universal ceremony.

## Stop conditions

Stop and ask for direction when:

- the target skill or authoritative supporting file is missing;
- two possible targets remain ambiguous;
- the requested update conflicts with a newer persistent version and cannot be reconciled safely;
- completion requires new external authority, credentials, installation, publication, or deletion not granted by the user;
- a runtime dependency cannot be verified and no safe fallback exists.

Otherwise complete the skill, validate it, and return the result without inserting an arbitrary grader threshold or approval checkpoint.
