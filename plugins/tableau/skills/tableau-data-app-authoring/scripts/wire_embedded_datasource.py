#!/usr/bin/env python3
"""
Deterministically wire an embedded (local file) datasource into a scaffolded
data-app `.twb`, as an alternative to wire_datasource.py's published-datasource
path. Same job, same two empty `<datasources />` anchors (workbook root + worksheet
`<view>`), same "fill both or fail" contract — but the connection is a local file
bundled inside the `.twbx` instead of a `sqlproxy` (Data Server) proxy to a
published datasource on a server.

Embedded connector types are supported, dispatched by file extension:
  - `.csv`   -> `federated`/`textscan` connection (column types regex-sniffed from
                sampled raw CSV rows).
  - `.xlsx`  -> `federated`/`excel-direct` connection (column types sniffed from the
                first sheet's cell `t` attributes via a stdlib zip/XML reader).
  - `.hyper` -> `federated`/`hyper` connection, WIRING-ONLY. A .hyper's schema is not
                stdlib-readable (and tableauhyperapi is out of scope), so the caller
                must supply a descriptor.json with a non-empty `fields` list; the
                fixed Extract relation shape is emitted from those fields.
  - `.zip`   -> `federated`/`ogrdirect` connection (spatial/shapefile). The field list
                is read from the zip's `.dbf` member via a minimal stdlib struct
                parser, plus a synthetic spatial `Geometry` field. Any `.zip` passed
                here is assumed (v1) to be a shapefile zip.

The CSV/`textscan` path is validated end-to-end (published and queried live from a
data-app extension). The Excel/`excel-direct`, Hyper/`hyper`, and shapefile/`ogrdirect`
paths have script-level support (this file emits the XML shape observed in real
Tableau-Desktop-authored workbooks) but their own live end-to-end validation happens
separately.

Each connector's introspection + root-XML builder lives in its own module under
`connectors/` (csv.py, excel.py, hyper.py, ogrdirect.py); shared helpers
(die/esc/derive_field) live in `connectors/common.py`. This file owns the CLI:
descriptor loading, the override-by-name mechanism, dispatch via the CONNECTORS
registry, anchor-splitting/replacement in the `.twb`, ref-count verification, and
the `Data/` copy step.

Unlike a published datasource, the file itself must ship inside the `.twbx`.
This script copies the source file to `<workspace root>/Data/<filename>` —
a directory that sits at the ARCHIVE ROOT alongside `Packages/`, never inside
it. Phase 3 packaging (SKILL.md) must zip `Data/` in addition to `Packages/`.

Column metadata is inferred directly from the file (header row + a sample of
data rows, integer/real/string) rather than requiring a hand-written descriptor
— there is no MCP introspection tool for a local file the way there is for a
published datasource. An optional descriptor can override inferred datatype/role
per field by name (and, for `.xlsx`, select a non-default sheet).

Usage:
  python3 wire_embedded_datasource.py <path-to.twb> <path-to.csv|.xlsx|.hyper|.zip> [descriptor.json]

descriptor.json (optional for .csv/.xlsx/.zip, REQUIRED for .hyper; overrides
inferred datatype/role for named fields):
  {
    "caption": "Tennis Players",              // optional, defaults from filename
    "connectionName": "federated.<hash>",     // optional, generated if omitted
    "sheet": "Sheet1",                         // optional, .xlsx only; defaults to first sheet
    "fields": [
      { "name": "career_singles_titles", "datatype": "integer", "role": "measure" }
    ]
  }

Exits non-zero with a diagnostic on any failure (missing/already-filled anchor,
empty input, drifted template) rather than emitting a broken workbook. Prints the
wired `.twb` path on stdout.
"""

import json
import os
import random
import re
import shutil
import string
import sys

from connectors import csv, excel, hyper, ogrdirect
from connectors.common import derive_field, die, esc

# The exact empty anchors emitted by the scaffold template. Matched literally.
EMPTY_ANCHOR = '<datasources />'


# --- connector registry ------------------------------------------------------
#
# One entry per supported extension, each pulled from its connector module's
# CONNECTOR dict. `named_prefix` is the named-connection's join-key prefix (the
# outer key is always `federated.<hash>`); `introspect` reads the file into
# columns; `build_root` emits the connector-specific root `<datasources>` block.
# The view-side XML is identical for every connector.

CONNECTORS = {
    '.csv': csv.CONNECTOR,
    '.xlsx': excel.CONNECTOR,
    '.hyper': hyper.CONNECTOR,
    '.zip': ogrdirect.CONNECTOR,
}


def main():
    argv = sys.argv
    if len(argv) < 3:
        die('Usage: python3 wire_embedded_datasource.py <path-to.twb> <path-to.csv|.xlsx> [descriptor.json]')
    twb_path_arg, source_path_arg = argv[1], argv[2]
    descriptor_path_arg = argv[3] if len(argv) > 3 else None

    twb_path = os.path.abspath(twb_path_arg)
    source_path = os.path.abspath(source_path_arg)
    ext = os.path.splitext(source_path)[1].lower()
    connector = CONNECTORS.get(ext)
    if connector is None:
        supported = ', '.join(sorted(CONNECTORS))
        die(f'Unsupported file type "{ext or os.path.basename(source_path)}" — supported extensions: {supported}.')
    if not os.path.exists(source_path):
        die(f"{connector['label']} not found at {source_path}")

    descriptor = {}
    if descriptor_path_arg:
        try:
            with open(descriptor_path_arg, 'r', encoding='utf-8') as f:
                descriptor = json.load(f)
        except Exception as error:
            die(f'Could not read/parse descriptor JSON at {descriptor_path_arg}: {error}')
            return

    # --- introspect the source file -----------------------------------------

    columns, meta = connector['introspect'](source_path, descriptor)

    overrides_by_name = {}
    for f in (descriptor.get('fields') if isinstance(descriptor.get('fields'), list) else []):
        if isinstance(f, dict) and 'name' in f:
            overrides_by_name[f['name']] = f

    names = [c['name'] for c in columns]
    fields = []
    for i, col in enumerate(columns):
        name = col['name']
        if not name:
            die(f"{connector['header_label']} has an empty column name at position {i}.")
        if names.index(name) != i:
            die(f'{connector["header_label"]} has a duplicate column name "{name}" at position {i} (already used at an earlier column) — rename one of the columns.')
        override = overrides_by_name.get(name)
        datatype = (override.get('datatype') if override else None) or col['datatype']
        override_role = override.get('role') if override else None
        role = override_role if override_role in ('measure', 'dimension') else ('measure' if datatype in ('integer', 'real') else 'dimension')
        fields.append(derive_field(name, datatype, role, i))

    filename = os.path.basename(source_path)
    table_base_name = os.path.splitext(filename)[0]
    caption = descriptor.get('caption') or re.sub(r'\b\w', lambda m: m.group(0).upper(), re.sub(r'[_-]+', ' ', table_base_name))

    # Single source of truth for the join key. Must start with "federated." — the
    # wiring is a federated connection wrapping a named connection (textscan for CSV,
    # excel-direct for Excel), not a bare sqlproxy the way a published datasource is.
    connection_name = descriptor.get('connectionName')
    if not connection_name:
        token = lambda: ''.join(random.choices(string.ascii_lowercase + string.digits, k=11))
        connection_name = f'federated.{token()}{token()}'[:37]
    if not connection_name.startswith('federated.'):
        die(f'connectionName must start with "federated." (got "{connection_name}").')
    named_connection_name = re.sub(r'^federated\.', connector['named_prefix'], connection_name)

    # --- copy the source file into Data/<filename> at the workspace root -----

    workspace_root = os.path.dirname(twb_path)
    data_dir = os.path.abspath(os.path.join(workspace_root, 'Data'))
    os.makedirs(data_dir, exist_ok=True)
    dest_path = os.path.join(data_dir, filename)
    shutil.copyfile(source_path, dest_path)

    # --- build the XML blocks ------------------------------------------------

    ctx = {
        'caption': caption,
        'connection_name': connection_name,
        'named_connection_name': named_connection_name,
        'filename': filename,
        'table_base_name': table_base_name,
        'fields': fields,
        'meta': meta,
    }
    root_datasource = connector['build_root'](ctx)

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
    # named_connection_name (textscan.<hash> / excel-direct.<hash>) appears: named-connection
    # name, relation connection = at least 2 references.
    named_ref_count = wired.count(f"'{named_connection_name}'")
    if named_ref_count < 2:
        die(f'Expected the named connection to appear >=2 times, saw {named_ref_count} — wiring incomplete.')

    with open(twb_path, 'w', encoding='utf-8') as f:
        f.write(wired)
    print(f"✓ Wired embedded {connector['label']} datasource '{caption}' ({connection_name}) with {len(fields)} field(s) into {twb_path}", file=sys.stderr)
    print(f'✓ Copied {filename} to {dest_path}', file=sys.stderr)
    print(twb_path)


if __name__ == '__main__':
    main()
