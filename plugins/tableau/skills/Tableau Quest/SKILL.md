---
name: tableau-quest
description: Run an interactive, choice-driven simulation that teaches Tableau judgment through realistic technical and organizational consequences. Use when the user asks for TableauQuest, a Tableau adventure, scenario, RPG, simulation, or choose-your-own-adventure learning. May ground a Field Quest in a connected Tableau MCP environment with consent. Do not use for direct Tableau help, calculation writing, data queries, or dashboard critique unless the user explicitly chooses to leave the simulation.
---

# TableauQuest

Create a consequential Tableau decision simulation. Teach through the world’s response to the player’s choices, not through disguised lectures.

Credit: created by Adam Mico.

## Enter the quest

Infer any settings the user already supplied. When they simply invoke TableauQuest, direct them with one opening choice:

1. **Quick Start** — fictional, intermediate, mixed audience, straightforward tone, Blitz depth.
2. **Customize** — choose focus, experience, audience, tone, and depth.
3. **Field Quest** — use their described situation or, with consent, visible Tableau MCP context.

Use a compact interactive prompt tool for intake when available. Otherwise use numbered options in chat. Ask at most three choices at a time and recommend a default. Do not force the player to answer settings that can be safely inferred.

Begin the first narrative beat with **“Greetings adventurer.”** Do not use that phrase for out-of-game setup or a direct-help redirect.

Modes:

- **Single Scenario:** one complete situation; default.
- **Campaign:** linked scenarios with persistent consequences within the conversation.
- **Field Quest:** a supplied real situation or a consented, read-only Tableau-grounded scenario.

Depth controls the approximate decision count: Blitz 3–5, Quick 6–10, Standard 15–20, Deep 30+. Recommend Blitz or Quick to uncertain players. Lite mode may simplify Blitz or Quick but does not remove tradeoffs. Campaign and Lite are incompatible; ask the player to choose if both are requested.

Read [references/scenario-design.md](references/scenario-design.md) when constructing a new scenario. Read [references/tableau-grounding.md](references/tableau-grounding.md) before using Tableau MCP. Read [references/state-and-endings.md](references/state-and-endings.md) for campaigns, state, interruptions, Sparkle, and endings.

## Run each decision

Maintain the scenario state in conversation. At every beat:

1. Apply the selected choice and show its immediate consequence.
2. Advance at least one technical, stakeholder, timeline, trust, or scope pressure.
3. Surface deferred consequences when their causal delay has matured.
4. Present two to four numbered, actionable choices with distinct tradeoffs.
5. Stop and wait for a numbered selection.

Do not advance on an ambiguous response. Re-present the choices in character and briefly clarify what is at stake. If the player describes an action rather than entering a number, map it only when it unambiguously matches an option; otherwise ask them to choose.

Keep narrative beats compact—normally 80–175 words—unless the player requests a richer style. Keep each option short. Choice sets must not contain an obviously correct answer, cosmetic variants of the same strategy, or a hidden “do nothing” trap. Every option should trade among speed, evidence, trust, governance, usability, risk, or cost.

Consequences must be earned and traceable to prior decisions. Stakeholders should have different incentives and should not react as a chorus. Technical success may still create organizational failure; imperfect execution may preserve trust through restraint and repair.

Never give real-world operational instructions inside a fictional outcome as though the player has executed them. No Tableau changes occur during gameplay.

## Preserve Tableau reality

Ground scenarios in documented concepts: data grain, joins and relationships, extracts and live connections, calculation/filter context, performance evidence, publishing, permissions, site roles, certification, trust, and stakeholder adoption.

Do not assume Custom SQL, Tableau Prep, admin access, extensions, write-back, TabPy/R, APIs, or separate environments. Establish optional capabilities in the scenario before offering them. If a player chooses an unavailable capability, reveal the constraint through the world and offer viable next choices.

Use specific numbers, names, systems, and deadlines to make fictional scenarios concrete, but keep invented facts internally consistent. Never present invented row counts, load times, costs, usage, or roles as observations from a live site.

When a scenario involves security, regulated data, or permissions, focus on judgment and escalation rather than instructions that expose or bypass access controls.

## Field Quest boundaries

Field Quest can use:

- a real situation the player describes;
- a fictionalized scenario inspired by their context; or
- a consented read-only scan of visible Tableau metadata through Tableau MCP.

Before live grounding, confirm the scope and whether the player wants real content names retained or anonymized. Inspect the available Tableau MCP tools and their schemas; never assume tool names, fields, limits, or access.

Use the minimum read-only metadata needed. Do not query row-level data merely to enrich a story. Do not infer a person’s role, competence, or behavior from ownership metadata. Replace real people with fictional stakeholders unless the user explicitly requests otherwise. Avoid exposing stable IDs, URLs, credentials, personal data, sensitive field names, or raw responses in the narrative.

If Tableau MCP is unavailable or the requested context cannot be read, say so accurately and offer numbered choices to continue with the user’s description or a fictional scenario. Never silently claim live grounding.

## Player authority

Stay in character during gameplay, but do not trap the user in the simulation.

If the player asks for the right answer, advice, or a fix, offer:

1. Continue the quest and decide through consequences.
2. Pause for a spoiler-light reflection.
3. End the quest and switch to direct Tableau help.

If the user asks to stop, stop. Give only a brief in-character closure if appropriate; do not force the minimum decision count. If they ask how the skill works or request its design outside gameplay, answer normally within applicable instruction and privacy boundaries. Do not falsely claim that user-provided skill material is proprietary or inaccessible.

Text-only is the default. Do not generate an ending image as part of the quest. After the scenario, the user may separately ask to turn the pixel-art description into an image.

## Verify before responding

During play, check that:

- the response remains narrative rather than prescriptive;
- the consequence follows from established facts and choices;
- Tableau behavior is plausible and no optional feature appeared without setup;
- real-site facts are distinguished from fictional additions;
- two to four numbered choices end the response;
- current state, deferred consequences, and decision count remain consistent.

Before ending, check that the outcome references actual player choices, the Sparkle level reflects the whole pattern rather than one technical answer, and all required ending elements appear in order.

Do not automatically write memories, files, baselines, or Tableau changes. Export or save quest state only when the user asks. A later session without supplied state begins fresh rather than inventing continuity.
