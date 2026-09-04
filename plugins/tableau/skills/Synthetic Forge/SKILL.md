---
name: codex-synth-forge
description: Generate deterministic, privacy-safe synthetic CSV, JSON, or SQLite datasets from a declarative profile, including multi-table foreign keys and validation. Use for reusable mock-data artifacts; do not use to query, reproduce, or quality-audit real records.
---

# Synthetic Forge

Create synthetic data with the bundled `scripts/synth_forge.py` CLI. Prefer a declarative profile over one-off generation code so the run is reproducible and testable.

## Choose the input path

- If the user supplies a profile, validate it with `profile-check` before generation.
- If the user describes a schema, translate it into the format in [references/profile-schema.md](references/profile-schema.md). Ask only about choices that materially affect types, row counts, relationships, distributions, or privacy.
- If the user supplies a Tableau datasource reference, use an available Tableau data tool only to derive aggregate metadata. Never persist raw rows or source examples. If no Tableau tool is available, request a profile or natural-language schema instead.

Do not use this skill when the user wants analysis of real data, a quality audit, production data extraction, or faithful reproduction of identifiable records.

## Privacy boundary

Profiles may contain aggregate distributions and common non-sensitive categories. They must not contain raw names, emails, phone numbers, addresses, account identifiers, free text, rare combinations, or example source rows. The CLI rejects the keys `source_values`, `raw_values`, and `sample_values` anywhere in a profile.

For stronger leakage protection, hash prohibited source values with SHA-256 outside the profile and place only the hashes in `privacy.forbidden_values_sha256`. Generated values are checked against them without storing the source values.

Use synthetic generators for identity-like fields. Do not convert a real value list into a categorical generator merely because the output is labeled synthetic.

## Generate

Work in a new output directory. The CLI stages the run beside the destination, validates it, then renames the staging directory into place. It refuses to replace an unrelated directory.

```bash
python scripts/synth_forge.py profile-check --profile profile.json
python scripts/synth_forge.py generate --profile profile.json --output outputs/run-001 --format csv --seed 42
```

Supported formats are `csv`, `json`, and `sqlite`. CSV and JSON use only the Python standard library. SQLite uses the standard-library `sqlite3` module.

If the requested output already contains a matching run fingerprint and still validates, generation returns it as a reusable result. A conflicting or damaged directory is a blocker; choose a new output directory rather than deleting it automatically.

## Verify and report

Every successful run contains:

- generated data files;
- `profile.normalized.json`;
- `validation.json` with row, type, null, range, uniqueness, relationship, and privacy gates;
- `manifest.json` with the run fingerprint and file hashes;
- `GENLOG.md` with a compact reproducibility summary.

Run an independent read-back check when needed:

```bash
python scripts/synth_forge.py validate --profile profile.json --data outputs/run-001
```

Do not call a run successful unless `validation.json` has `ok: true`. Report the seed, fingerprint, format, row counts, and any deliberately unsupported request. Never call untested statistical resemblance “calibrated”; only claim the constraints represented and validated by the profile.

## Failure handling

- Profile errors: correct the profile or ask for the missing decision; do not guess relationships or sensitive categories.
- Validation failure: leave the staging directory quarantined and report its exact path and failed gates.
- Unsupported generator or format: stop and list supported choices.
- Output conflict: use a new destination. Do not add a force-delete path.
- Missing Tableau access: continue from a profile or schema; do not invent datasource metadata.

For implementation changes, run `python -m unittest discover -s scripts/tests -v` and the active skill validator before handoff.
