# Tableau Dashboard Blueprint

A Codex skill for turning business questions, audience needs, and Tableau datasource metadata into an implementation-ready dashboard design.

## What it provides

- audience- and decision-centered requirements;
- evidence-aware question-to-field mapping;
- chart, KPI, layout, filter, action, tooltip, and responsive specifications;
- accessible color and typography guidance;
- Tableau implementation notes without unsupported performance claims;
- deterministic HTML wireframes from a validated JSON contract.

The skill is a planning tool. It does not build or publish a Tableau workbook unless the user separately requests and authorizes that work.

## Example prompts

- `Design an executive Tableau dashboard for regional sales performance.`
- `Given this datasource, what charts should I build for a support manager?`
- `Create a two-page blueprint for pipeline monitoring and diagnosis.`
- `Turn this dashboard specification into a visual HTML wireframe.`
- `Adapt the blueprint for desktop and tablet layouts.`

## Package layout

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Core workflow, routing, and authority boundaries |
| `references/intake-and-data.md` | Evidence gathering and field mapping |
| `references/chart-selection.md` | Analytical-task chart guidance |
| `references/layout-and-interaction.md` | Page, filter, action, and tooltip design |
| `references/visual-system.md` | Color, typography, branding, and accessibility |
| `references/tableau-implementation.md` | Tableau build handoff and verification |
| `references/output-contract.md` | Blueprint structure and quality checks |
| `references/wireframe-contract.md` | Renderer JSON schema |
| `scripts/render_wireframe.py` | Safe, self-contained HTML renderer |
| `scripts/tests/test_render_wireframe.py` | Validation, safety, and portability tests |

## Local validation

```bash
python -m unittest discover -s scripts/tests -v
python -m py_compile scripts/render_wireframe.py
```

Render from any working directory using absolute paths:

```bash
python /absolute/path/to/tableau-dashboard-blueprint/scripts/render_wireframe.py /absolute/path/to/spec.json /absolute/path/to/wireframe.html
```

The renderer rejects overlapping or out-of-bounds zones, unsafe schema extensions, invalid dimensions/colors, malformed input, and accidental output replacement. User-controlled text is HTML-escaped.
