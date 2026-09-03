# Synthetic Forge

Synthetic Forge generates deterministic, privacy-safe synthetic datasets from declarative profiles. It supports related tables, reproducible seeds, CSV/JSON/SQLite output, read-back validation, and manifest-based rerun checks.

## When to use it

- Generate reusable mock data for development, demos, and tests.
- Model multi-table datasets with validated foreign keys.
- Reproduce a dataset exactly from a profile and seed.
- Create output artifacts without copying real records.

Do not use it to query, reproduce, or quality-audit production data.

## Requirements

- Codex with this skill installed or available.
- Python 3.10+.

CSV, JSON, and SQLite generation use only the Python standard library.

## Installation

Install the entire `codex-synth-forge` directory through your normal Codex skill or plugin workflow. Keep `SKILL.md`, `agents/`, `references/`, and `scripts/` together.

## Quick start

Validate a profile:

```bash
python scripts/synth_forge.py profile-check --profile profile.json
```

Generate a deterministic CSV dataset:

```bash
python scripts/synth_forge.py generate \
  --profile profile.json \
  --output outputs/run-001 \
  --format csv \
  --seed 42
```

Read the generated artifacts back and validate them independently:

```bash
python scripts/synth_forge.py validate \
  --profile profile.json \
  --data outputs/run-001
```

## Example prompt

```text
Use $codex-synth-forge to generate 5,000 customers and 25,000 related orders as CSV. Make email addresses synthetic, preserve referential integrity, and use seed 42.
```

## Output contract

Each successful run includes generated data plus:

- `profile.normalized.json` — canonical input profile;
- `validation.json` — row, type, null, range, uniqueness, relationship, and privacy checks;
- `manifest.json` — run fingerprint and file hashes;
- `GENLOG.md` — compact reproducibility summary.

A run is successful only when `validation.json` reports `ok: true`.

## Privacy model

Profiles may contain aggregate distributions and common non-sensitive categories. They must not contain raw identities, contact details, account identifiers, free text, rare combinations, or source rows. Identity-like values are generated synthetically.

For leakage checks without storing prohibited source values, the profile can contain SHA-256 hashes in `privacy.forbidden_values_sha256`.

## Development

Run the complete test suite and active Codex skill validator before release:

```bash
python -m unittest discover -s scripts/tests -v
```

## License

No license has been assigned by this package. Add one before public redistribution.
