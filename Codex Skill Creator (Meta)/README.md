# Codex Skill Creator

Codex Skill Creator helps Codex design and maintain installable skills with precise triggers, appropriately scoped instructions, and only the resources that materially improve execution.

## When to use it

- Create a new `SKILL.md` and supporting package.
- Refactor an oversized skill using progressive disclosure.
- Add a deterministic helper, reference, asset, or invocation metadata.
- Repair trigger precision, conflicting instructions, broken resource links, or unsafe mutation behavior.

It is not a skill grader and is not intended merely to execute or troubleshoot another skill.

## Principles

- Preserve the user's actual scope and authorization boundaries.
- Assume Codex already has broad general capability.
- Add prescriptive detail only where reliability, safety, or a fragile workflow requires it.
- Keep discovery metadata concise and discriminating.
- Put conditional detail in `references/`, reusable mechanics in `scripts/`, and output ingredients in `assets/`.
- Validate observable behavior rather than checking for ceremonial headings or keywords.

## Installation

Install the entire `codex-skill-creator` directory through your normal Codex skill or plugin workflow. Keep `SKILL.md` and `agents/` together.

## Example prompts

```text
Use $codex-skill-creator to turn this workflow into an installable skill with a concise entrypoint and a routed schema reference.
```

```text
Refactor this skill so it triggers less broadly and move its provider-specific instructions into references.
```

```text
Add a tested helper for the deterministic file transformation this skill currently reimplements in prose.
```

## Expected package

Every installable skill has a `SKILL.md`. Other resources are optional:

```text
skill-name/
├── SKILL.md
├── agents/openai.yaml
├── scripts/
├── references/
└── assets/
```

The smallest package that reliably supports the capability is preferred. Empty directories, duplicated guides, fictional dependencies, and self-grades do not improve a skill.

## Validation

Use the validator supplied by the active Codex skill-creation environment. Also verify resource links, helper success and failure behavior, runtime dependencies, mutation controls, and realistic trigger/boundary behavior.

## License

No license has been assigned by this package. Add one before public redistribution.
