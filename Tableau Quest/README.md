# TableauQuest for Codex

TableauQuest is a choice-driven simulation skill that teaches Tableau judgment through realistic technical and organizational consequences.

Created by [Adam Mico](https://www.linkedin.com/in/adammico/).

## Features

- Single scenarios, campaigns, and Field Quests.
- Blitz through Deep session lengths.
- Consequence-driven choices without obvious correct answers.
- Tableau-realistic constraints spanning performance, governance, metrics, reliability, security, UX, and organizational trust.
- Optional, consented read-only grounding through a connected Tableau MCP server.
- Text-only pixel-art endings and a judgment-based Sparkle evaluation.

## Requirements

- Codex.
- Optional Tableau MCP connection for live-grounded Field Quests.

The skill runs fully with fictional scenarios when no Tableau connection is available.

## Example prompts

```text
Use $tableau-quest to start a quick Tableau adventure.
```

```text
Start TableauQuest in noir mode. I am an advanced developer and want a metric-conflict scenario.
```

```text
Use $tableau-quest for a Field Quest based on my Tableau project. Anonymize all people and keep the scan read-only.
```

## Package contents

- `SKILL.md` — Codex entrypoint and gameplay contract.
- `agents/openai.yaml` — discovery metadata and optional Tableau MCP dependency.
- `references/scenario-design.md` — scenario archetypes, realism, choices, and calibration.
- `references/tableau-grounding.md` — consent, MCP discovery, evidence semantics, and privacy.
- `references/state-and-endings.md` — state, campaigns, interruptions, Sparkle, and endings.
- `scripts/validate_state.py` — validator for exported/restored quest state.
- `scripts/test_validate_state.py` — validator unit tests.

## Safety and privacy

Field Quest uses only the minimum read-only metadata needed. It does not place real owners into fictional negative roles, expose raw responses, or modify Tableau content. It distinguishes observed site facts from fictional story details.

## State

Quest state remains in the current conversation by default. The skill does not automatically write memory or files. Users may explicitly export structured state and validate it with:

```bash
python scripts/validate_state.py state.json
```

## Validation status

Local package and unit tests can verify structure and state invariants. A live forward test requires a separate Codex session connected to Tableau MCP.

## License

No license is asserted by this conversion. Add one only if you have the right to do so.
