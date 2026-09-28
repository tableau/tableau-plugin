#!/usr/bin/env python3
"""
Deterministically wire an embedded (local file) datasource into a scaffolded
data-app `.twb`, as an alternative to wire_datasource.py's published-datasource
path. Same job, same two empty `<datasources />` anchors (workbook root + worksheet
`<view>`), same "fill both or fail" contract — but the connection is a `textscan`
(CSV) file bundled inside the `.twbx` instead of a `sqlproxy` (Data Server) proxy
to a published datasource on a server.

CSV only, for now: Tableau also supports embedding Excel (`excel-direct`), other
local file types, and true embedded Hyper extracts (`hyper`, via the Hyper API),
but only the CSV/`textscan` path has been validated end-to-end (published and
queried live from a data-app extension). Extending this script to other file
types would need its own validation pass first.

Unlike a published datasource, the file itself must ship inside the `.twbx`.
This script copies the source file to `<workspace root>/Data/<filename>` —
a directory that sits at the ARCHIVE ROOT alongside `Packages/`, never inside
it. Phase 3 packaging (SKILL.md) must zip `Data/` in addition to `Packages/`.

Column metadata is inferred directly from the CSV (header row + a sample of
data rows, integer/real/string) rather than requiring a hand-written descriptor
— there is no MCP introspection tool for a local file the way there is for a
published datasource. An optional descriptor can override inferred datatype/role
per field by name.

Usage:
  python3 wire_embedded_datasource.py <path-to.twb> <path-to.csv> [descriptor.json]

descriptor.json (optional; overrides inferred datatype/role for named fields):
  {
    "caption": "Tennis Players",              // optional, defaults from filename
    "connectionName": "federated.<hash>",     // optional, generated if omitted
    "fields": [
      { "name": "career_singles_titles", "datatype": "integer", "role": "measure" }
    ]
  }

Exits non-zero with a diagnostic on any failure (missing/already-filled anchor,
empty CSV, drifted template) rather than emitting a broken workbook. Prints the
wired `.twb` path on stdout.
"""

import json
import os
import random
import re
import shutil
import string
import sys

# The exact empty anchors emitted by the scaffold template. Matched literally.
EMPTY_ANCHOR = '<datasources />'


def die(message):
    print(f'✗ {message}', file=sys.stderr)
    sys.exit(1)


# XML attribute-value escaping (single-quoted attrs + element text).
def esc(value):
    return (
        str(value)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace("'", '&apos;')
        .replace('"', '&quot;')
    )


# Minimal CSV line splitter: no embedded-comma/quote support. Good enough for the
# flat, simple CSVs this path is meant for; a quoted-field CSV needs a real parser.
def split_csv_line(line):
    return [cell.strip() for cell in line.split(',')]


def infer_datatype(values):
    non_empty = [v for v in values if v != '']
    if len(non_empty) == 0:
        return 'string'
    if all(re.fullmatch(r'-?\d+', v) for v in non_empty):
        return 'integer'
    if all(re.fullmatch(r'-?\d+(\.\d+)?', v) for v in non_empty):
        return 'real'
    return 'string'


# datatype -> Tableau column `type`.
def type_of(datatype):
    return 'quantitative' if datatype in ('real', 'integer') else 'nominal'


# A field's derived attributes, computed once and reused across all blocks so the
# root metadata-record, the root column, the view column, and the column-instance
# all agree — mirrors wire_datasource.py's derive_field.
def derive_field(name, datatype, role, ordinal):
    is_measure = role == 'measure'
    field_type = type_of(datatype)
    return {
        'name': name,
        'datatype': datatype,
        'role': role,
        'type': field_type,
        'ordinal': ordinal,
        'aggregation': 'Sum' if is_measure else 'Count',
        'localName': f'[{name}]',
        'derivation': 'Sum' if is_measure else 'None',
        'instanceName': f'[sum:{name}:qk]' if is_measure else f'[none:{name}:nk]',
    }


def main():
    argv = sys.argv
    if len(argv) < 3:
        die('Usage: python3 wire_embedded_datasource.py <path-to.twb> <path-to.csv> [descriptor.json]')
    twb_path_arg, csv_path_arg = argv[1], argv[2]
    descriptor_path_arg = argv[3] if len(argv) > 3 else None

    twb_path = os.path.abspath(twb_path_arg)
    csv_path = os.path.abspath(csv_path_arg)
    if os.path.splitext(csv_path)[1].lower() != '.csv':
        die(f'Only .csv files are supported by this script (got "{os.path.basename(csv_path)}"). See file header for other embedded-file types (unvalidated).')
    if not os.path.exists(csv_path):
        die(f'CSV not found at {csv_path}')

    descriptor = {}
    if descriptor_path_arg:
        try:
            with open(descriptor_path_arg, 'r', encoding='utf-8') as f:
                descriptor = json.load(f)
        except Exception as error:
            die(f'Could not read/parse descriptor JSON at {descriptor_path_arg}: {error}')
            return

    # --- read + infer from the CSV ------------------------------------------

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            raw = f.read()
    except Exception as error:
        die(f'Could not read CSV at {csv_path}: {error}')
        return
    csv_lines = [line for line in re.split(r'\r\n|\r|\n', raw) if len(line) > 0]
    if len(csv_lines) < 2:
        die('CSV must have a header row plus at least one data row.')

    header = split_csv_line(csv_lines[0])
    sample_rows = [split_csv_line(line) for line in csv_lines[1:201]]  # sample up to 200 rows for type inference

    overrides_by_name = {}
    for f in (descriptor.get('fields') if isinstance(descriptor.get('fields'), list) else []):
        if isinstance(f, dict) and 'name' in f:
            overrides_by_name[f['name']] = f

    fields = []
    for i, name in enumerate(header):
        if not name:
            die(f'CSV header has an empty column name at position {i}.')
        if header.index(name) != i:
            die(f'CSV header has a duplicate column name "{name}" at position {i} (already used at an earlier column) — rename one of the columns.')
        override = overrides_by_name.get(name)
        column_values = [(row[i] if i < len(row) else '') for row in sample_rows]
        datatype = (override.get('datatype') if override else None) or infer_datatype(column_values)
        override_role = override.get('role') if override else None
        role = override_role if override_role in ('measure', 'dimension') else ('measure' if datatype in ('integer', 'real') else 'dimension')
        fields.append(derive_field(name, datatype, role, i))

    filename = os.path.basename(csv_path)
    table_base_name = os.path.splitext(filename)[0]
    caption = descriptor.get('caption') or re.sub(r'\b\w', lambda m: m.group(0).upper(), re.sub(r'[_-]+', ' ', table_base_name))

    # Single source of truth for the join key. Must start with "federated." — the
    # wiring is a federated connection wrapping a named textscan connection, not a
    # bare sqlproxy the way a published datasource is.
    connection_name = descriptor.get('connectionName')
    if not connection_name:
        token = lambda: ''.join(random.choices(string.ascii_lowercase + string.digits, k=11))
        connection_name = f'federated.{token()}{token()}'[:37]
    if not connection_name.startswith('federated.'):
        die(f'connectionName must start with "federated." (got "{connection_name}").')
    named_connection_name = re.sub(r'^federated\.', 'textscan.', connection_name)

    # --- copy the CSV into Data/<filename> at the workspace root -------------

    workspace_root = os.path.dirname(twb_path)
    data_dir = os.path.abspath(os.path.join(workspace_root, 'Data'))
    os.makedirs(data_dir, exist_ok=True)
    dest_csv_path = os.path.join(data_dir, filename)
    shutil.copyfile(csv_path, dest_csv_path)

    # --- build the XML blocks ------------------------------------------------

    metadata_records = '\n'.join(
        f"""          <metadata-record class='column'>
            <remote-name>{esc(f['name'])}</remote-name>
            <remote-type>{5 if f['type'] == 'quantitative' else 129}</remote-type>
            <local-name>{esc(f['localName'])}</local-name>
            <parent-name>[{esc(filename)}]</parent-name>
            <remote-alias>{esc(f['name'])}</remote-alias>
            <ordinal>{f['ordinal']}</ordinal>
            <local-type>{esc(f['datatype'])}</local-type>
            <aggregation>{f['aggregation']}</aggregation>
            <contains-null>true</contains-null>
          </metadata-record>"""
        for f in fields
    )

    root_columns = '\n'.join(
        f"      <column datatype='{esc(f['datatype'])}' name='{esc(f['localName'])}' role='{f['role']}' type='{f['type']}' />"
        for f in fields
    )

    root_datasource = f"""<datasources>
    <datasource caption='{esc(caption)}' inline='true' name='{esc(connection_name)}' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='{esc(filename)}' name='{esc(named_connection_name)}'>
            <connection class='textscan' directory='Data' filename='{esc(filename)}' password='' server='' />
          </named-connection>
        </named-connections>
        <relation connection='{esc(named_connection_name)}' name='{esc(filename)}' table='[{esc(table_base_name)}#csv]' type='table' />
        <metadata-records>
{metadata_records}
        </metadata-records>
      </connection>
      <aliases enabled='yes' />
{root_columns}
    </datasource>
  </datasources>"""

    view_columns = '\n'.join(
        f"            <column aggregation='{f['aggregation']}' datatype='{esc(f['datatype'])}' name='{esc(f['localName'])}' role='{f['role']}' type='{f['type']}' />"
        for f in fields
    )

    view_column_instances = '\n'.join(
        f"            <column-instance column='{esc(f['localName'])}' derivation='{f['derivation']}' name='{esc(f['instanceName'])}' pivot='key' type='{f['type']}' />"
        for f in fields
    )

    view_datasources = f"""<datasources>
            <datasource caption='{esc(caption)}' name='{esc(connection_name)}' />
          </datasources>
          <datasource-dependencies datasource='{esc(connection_name)}'>
{view_columns}
{view_column_instances}
          </datasource-dependencies>"""

    # --- apply, splitting on <worksheets> so each anchor is unambiguous ------

    try:
        with open(twb_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as error:
        die(f'Could not read .twb at {twb_path}: {error}')
        return

    split_idx = content.find('<worksheets>')
    if split_idx == -1:
        die('No <worksheets> element found — is this a scaffolded data-app .twb?')
    head = content[:split_idx]
    tail = content[split_idx:]

    # Root anchor lives in the head (before <worksheets>).
    if EMPTY_ANCHOR not in head:
        die(f'Root "{EMPTY_ANCHOR}" anchor not found before <worksheets> — already wired or template drifted.')
    head = head.replace(EMPTY_ANCHOR, root_datasource, 1)

    # View anchor is the first empty <datasources /> inside the worksheets section.
    if EMPTY_ANCHOR not in tail:
        die(f'View "{EMPTY_ANCHOR}" anchor not found inside <worksheets> — already wired or template drifted.')
    tail = tail.replace(EMPTY_ANCHOR, view_datasources, 1)

    wired = head + tail

    # --- verify before writing ----------------------------------------------

    if EMPTY_ANCHOR in wired:
        die('An empty <datasources /> anchor survived wiring — refusing to write a half-wired workbook.')
    # Unlike wire_datasource.py's bare sqlproxy, the relation here joins through the
    # named connection's own key, not the outer federated one — so the two join keys
    # must be verified separately rather than expecting one string 4 times.
    #
    # connection_name (federated.<hash>) appears: root datasource name, view datasource
    # name, datasource-dependencies datasource = at least 3 references.
    ref_count = wired.count(f"'{connection_name}'")
    if ref_count < 3:
        die(f'Expected the connection name to appear >=3 times, saw {ref_count} — wiring incomplete.')
    # named_connection_name (textscan.<hash>) appears: named-connection name, relation
    # connection = at least 2 references.
    named_ref_count = wired.count(f"'{named_connection_name}'")
    if named_ref_count < 2:
        die(f'Expected the named connection to appear >=2 times, saw {named_ref_count} — wiring incomplete.')

    with open(twb_path, 'w', encoding='utf-8') as f:
        f.write(wired)
    print(f"✓ Wired embedded CSV datasource '{caption}' ({connection_name}) with {len(fields)} field(s) into {twb_path}", file=sys.stderr)
    print(f'✓ Copied {filename} to {dest_csv_path}', file=sys.stderr)
    print(twb_path)


if __name__ == '__main__':
    main()
