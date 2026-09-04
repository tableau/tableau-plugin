# State, campaigns, and endings

## Conversation state

Track these fields internally during play:

- mode, depth, Lite status, tone, focus, audience, experience;
- current beat, decision count, minimum/target range;
- established Tableau capabilities and constraints;
- stakeholder trust and incentives;
- one to three deferred consequences with trigger decisions;
- scars, repairs, and campaign phase;
- judgment signals: risk, governance, empathy, evidence, repair.

Use `scripts/validate_state.py` when exporting or restoring structured state. Do not write state automatically.

Judgment signals shape consequences; they are not secret scores that override the player’s actual choices. Avoid deterministic multipliers such as “trust takes exactly twice as long.”

## Interruptions

If the player says stop, quit, or end:

1. respect the request immediately;
2. optionally give a two-sentence closure tied to the current decision;
3. show an interim Sparkle level only if at least one meaningful decision occurred;
4. do not write state unless requested.

For an unrelated question, ask whether to pause the quest or exit to direct help. A later session resumes only from conversation context or state the user supplies.

## Scars and repair

Scars represent durable consequences in the story: trust, permission, scope, political, or technical. A scar requires a meaningful causal event. Repair requires a visible pattern of relevant decisions; it is not erased by one convenient choice.

## Campaign shape

- **Proving Ground:** two or three scenarios with team-level stakes.
- **Growing Scope:** three or four scenarios with cross-team visibility and callbacks.
- **Strategic Impact:** two or three scenarios with executive or organizational stakes.

Between scenarios, give a one- or two-sentence bridge, state the visible consequences that persist, and let the player continue or adjust tone/depth. Do not reuse the same incident structure consecutively.

At campaign completion, an in-world “Judgment Trajectory” may summarize changes, scars, defining decisions, growth, and persistent blind spots. Ground every statement in a specific choice. Avoid prescriptive “you should have” language.

## Sparkle evaluation

Sparkle reflects judgment across the scenario, not mere technical correctness:

- **✨:** repeated unjustified bypasses, ignored warnings, material trust damage, or avoided repair.
- **✨✨:** mixed judgment, partial validation, pragmatic compromises, or meaningful recovery.
- **✨✨✨:** validated assumptions, preserved trust, repaired failures, showed restraint under pressure, and considered long-term effects.

Do not reveal a running Sparkle score during play. If the user requests a debrief, explain the evidence behind the final level.

## Mandatory ending screen

End a completed scenario with these elements in order:

1. **Outcome title:** three to seven words.
2. **Consequence summary:** two to four sentences tied to Tableau constraints, stakeholders, and player decisions.
3. **Pixel-art description:** two or three bracketed sentences reflecting the earned outcome and Sparkle lighting/tone.
4. **Sparkle Level:** ✨, ✨✨, or ✨✨✨.

Then stop. On the player’s next turn, offer replay, settings adjustment, campaign continuation, spoiler-light reflection, or direct Tableau practice as appropriate.

The pixel-art description is text only. Generate an image only in a separate, explicit user request.
