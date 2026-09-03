---
name: viz-critique-pro
description: Review and score Tableau dashboards or views from a render plus available Tableau metadata, using an evidence-based seven-domain rubric and prioritized recommendations. Use for critique or scoring; do not use to edit workbooks, validate underlying data accuracy, or assess business performance.
---

# Viz Critique Pro

Evaluate the visualization first and advise second. Ground every score in visible evidence, distinguish observation from inference, and keep review work read-only.

## Resolve the target

Accept any of these inputs:

- an attached screenshot or render;
- a Tableau view or workbook URL;
- a Tableau content name or canonical identifier;
- a workbook with a user-specified view to review.

When a Tableau MCP server is available, discover its actual search/list, metadata, and view-image capabilities before calling them. Resolve names and URLs to the canonical identifier returned by the server; do not assume a numeric route segment is an API identifier. Use only read operations.

For a workbook with several relevant views, use the view the user named. If none was named and the choice would change the review, ask which view to score; otherwise state the selected view and why it is representative. Review every view only when the user requests workbook-wide coverage.

Fetch the largest practical render without distorting its intended aspect ratio. Metadata may establish owner, project, device layout, view names, or intended audience, but it is not evidence for a visual quality that is absent from the render.

If the render is too small, clipped, blank, or stale enough to make scoring unreliable, request a better image instead of guessing. A screenshot supplied directly by the user does not require Tableau access.

## Establish context

Before scoring, identify:

- the dominant genre: business dashboard, analytical/exploratory, narrative, editorial, expressive/data art, or scientific/technical;
- the likely audience and time budget when supported by the request or artifact;
- the primary question the visualization appears to answer.

State the primary question in the review. Mark it **unclear** when the evidence does not support one. Do not penalize a narrative, analytical, or expressive visualization for lacking dashboard conventions that do not serve its genre.

## Score from evidence

Read [rubric.md](references/rubric.md) before assigning scores. Catalog meaningful strengths before gaps, but do not use a predetermined passing floor. Score each domain from 0–10 against its anchor descriptions and cite observable evidence for both high scores and material deductions.

Assess visible interactivity cues—filters, controls, navigation, selection state, and disclosure model—inside Audience Adaptation and Layout. Do not claim tooltip quality, action responsiveness, keyboard support, screen-reader structure, or parameter behavior from a static render.

Record the seven base scores, documented adjustments, and applicable caps in a JSON assessment. Read [assessment-schema.md](references/assessment-schema.md) for the required shape and adjustment identifiers.

Resolve `skill_dir` as the absolute directory containing this `SKILL.md`; do not assume the skill is the current working directory. Then use the bundled helper for deterministic weighting, validation, half-even rounding, safety status, and tier assignment:

```bash
python3 "$skill_dir/scripts/score_viz.py" "/absolute/path/to/assessment.json"
```

The helper is the arithmetic authority, not the visual evaluator. Never manufacture an adjustment merely to reach a tier. When it returns `safety_status: blocked`, display `Safety remediation required` instead of a quality tier and lead with the blocking issue.

If any domain genuinely cannot be assessed, do not invent a value or calculate an overall score. Deliver the supported qualitative findings, mark the missing domain, and request the evidence needed for a complete score.

## Deliver the review

Default to a complete but compact inline review unless the user requested a brief answer or a file. Do not delay useful findings behind a mandatory format question.

Include:

1. final score, tier, genre, and primary question;
2. a short verdict;
3. the seven-domain scorecard with concrete evidence;
4. the main score drivers and any cap;
5. two to four prioritized recommendations.

For each recommendation, describe the current issue, the proposed change, the affected domain, and a coarse effort level such as Low, Medium, or High. Give numeric uplift or time estimates only when the evidence supports them; otherwise avoid false precision.

Read [report-guide.md](references/report-guide.md) when the user requests a detailed review, multiple views, or a document artifact. If a `.docx`, Google Doc, or another format is requested, use the appropriate available document capability and preserve the same evidence and score.

Keep humor light and never use it when discussing misleading presentation, accessibility barriers, or exposed sensitive data.

## Boundaries

- Review-only requests do not authorize workbook edits, publishing, comments, subscriptions, or other Tableau mutations.
- Route an authorized workbook repair to a workbook-authoring skill when available; do not silently change scope.
- Visual design review does not validate source data, calculation correctness, business conclusions, or performance unless the user supplies separate evidence and requests that analysis.
- Treat visible personal or sensitive data as evidence to minimize in the report, not content to reproduce.
- When only a static image is available, label interaction and accessibility limitations explicitly.

For implementation changes, run `python -m unittest discover -s scripts/tests -v` and the active skill validator.
