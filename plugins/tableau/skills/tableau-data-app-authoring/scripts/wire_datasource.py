#!/usr/bin/env python3
"""
Wire a published datasource into a scaffolded data-app `.twb`.

`scaffold-data-app` emits a workbook with TWO empty `<datasources />` anchors
(workbook root + worksheet `<view>`). Until both are filled the extension's
`getAllDataSourcesAsync()` finds nothing and renders "no data source found in
the workbook." This fills both with one published `sqlproxy` (Data Server)
datasource, keeping the `sqlproxy.<hash>` join key byte-identical everywhere.

A script, not freehand XML, because the wiring spans four locations that must
agree exactly (root datasource `name`, root `relation connection`, view
`datasource name`, `datasource-dependencies datasource`); miss one and the
workbook silently reaches no data.

Usage: python3 wire_datasource.py <path-to.twb> <descriptor.json>

descriptor.json (Claude assembles from list-datasources + get-datasource-metadata;
list ONLY the fields the app will query):
  {
    "caption":      "Superstore Datasource",
    "repositoryId": "SuperstoreDatasource",   // published DS contentUrl (== repo-location id / dbname)
    "site":         "mcp-test",
    "server":       "10ax.online.tableau.com",
    "channel":      "https",   // optional, default https
    "port":         443,       // optional, default 443 (use http/80 for on-prem)
    "connectionName": "sqlproxy.<hash>",  // optional, generated if omitted
    "fields": [
      { "name": "Profit", "datatype": "real",   "role": "measure"   },
      { "name": "Region", "datatype": "string", "role": "dimension" }
    ]
  }
"""

import json
import os
import random
import string
import sys

# The exact empty anchor emitted by the scaffold template. Matched literally.
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


# datatype -> Tableau column `type`.
def type_of(datatype):
    d = str(datatype).lower()
    if d in ('real', 'integer'):
        return 'quantitative'
    if d in ('date', 'datetime'):
        return 'ordinal'
    return 'nominal'


# Derive a field's attributes once, reused across the root metadata-record, view
# column, and column-instance so all three agree.
def derive_field(field, ordinal):
    name = field.get('name') if isinstance(field, dict) else None
    if not name or not isinstance(name, str):
        die(f'Every field needs a string "name" (field #{ordinal} was {json.dumps(field, separators=(",", ":"))}).')
    datatype = str(field.get('datatype') or 'string').lower()
    role = 'measure' if field.get('role') == 'measure' else 'dimension'
    is_measure = role == 'measure'
    field_type = type_of(datatype)
    return {
        'name': name,
        'datatype': datatype,
        'role': role,
        'type': field_type,
        'ordinal': ordinal,
        'aggregation': 'Sum' if is_measure else 'Count',
        # role attribute: 0 = dimension, 1 = measure
        'roleAttr': 1 if is_measure else 0,
        'localName': f'[{name}]',
        # column-instance derivation + name token: [sum:Profit:qk] / [none:Region:nk]
        'derivation': 'Sum' if is_measure else 'None',
        'instanceName': f'[sum:{name}:qk]' if is_measure else f'[none:{name}:nk]',
    }


def main():
    argv = sys.argv
    if len(argv) < 3:
        die('Usage: python3 wire_datasource.py <path-to.twb> <descriptor.json>')
    twb_path_arg, descriptor_path_arg = argv[1], argv[2]
    twb_path = os.path.abspath(twb_path_arg)

    try:
        with open(descriptor_path_arg, 'r', encoding='utf-8') as f:
            descriptor = json.load(f)
    except Exception as error:
        die(f'Could not read/parse descriptor JSON at {descriptor_path_arg}: {error}')
        return

    for key in ('caption', 'repositoryId', 'site', 'server'):
        value = descriptor.get(key)
        if not value or not isinstance(value, str):
            die(f'Descriptor is missing required string "{key}".')
    caption, repository_id, site, server = (
        descriptor['caption'],
        descriptor['repositoryId'],
        descriptor['site'],
        descriptor['server'],
    )
    channel = descriptor.get('channel') or 'https'
    port = descriptor.get('port') if descriptor.get('port') is not None else (443 if channel == 'https' else 80)

    fields_in = descriptor.get('fields') if isinstance(descriptor.get('fields'), list) else []
    if len(fields_in) == 0:
        die('Descriptor "fields" must list at least one field the app will query.')
    fields = [derive_field(f, i) for i, f in enumerate(fields_in)]

    # Single source of truth for the join key.
    connection_name = descriptor.get('connectionName')
    if not connection_name:
        token = lambda: ''.join(random.choices(string.ascii_lowercase + string.digits, k=11))
        connection_name = f'sqlproxy.{token()}{token()}'[:37]
    if not connection_name.startswith('sqlproxy.'):
        die(f'connectionName must start with "sqlproxy." (got "{connection_name}").')

    # --- build the XML blocks ----------------------------------------------

    metadata_records = '\n'.join(
        f"""          <metadata-record class='column'>
            <remote-name>{esc(f['name'])}</remote-name>
            <remote-type>{5 if f['type'] == 'quantitative' else 129}</remote-type>
            <local-name>{esc(f['localName'])}</local-name>
            <parent-name>[sqlproxy]</parent-name>
            <remote-alias>{esc(f['name'])}</remote-alias>
            <ordinal>{f['ordinal']}</ordinal>
            <layered>true</layered>
            <local-type>{esc(f['datatype'])}</local-type>
            <aggregation>{f['aggregation']}</aggregation>
            <contains-null>true</contains-null>
            <attributes>
              <attribute datatype='integer' name='field-type'>1</attribute>
              <attribute datatype='integer' name='role'>{f['roleAttr']}</attribute>
            </attributes>
          </metadata-record>"""
        for f in fields
    )

    root_datasource = f"""<datasources>
    <datasource caption='{esc(caption)}' inline='true' name='{esc(connection_name)}' version='18.1'>
      <repository-location id='{esc(repository_id)}' path='/t/{esc(site)}/datasources' revision='1.0' site='{esc(site)}' />
      <connection channel='{esc(channel)}' class='sqlproxy' dbname='{esc(repository_id)}' directory='dataserver' port='{esc(port)}' server='{esc(server)}' server-ds-friendly-name='{esc(caption)}' username=''>
        <relation type='collection'>
          <relation connection='{esc(connection_name)}' name='sqlproxy' table='[sqlproxy]' type='table' />
        </relation>
        <metadata-records>
{metadata_records}
        </metadata-records>
      </connection>
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
    # Join key must appear >=4x: root datasource name, root relation connection,
    # view datasource name, datasource-dependencies datasource.
    ref_count = wired.count(f"'{connection_name}'")
    if ref_count < 4:
        die(f'Expected the connection name to appear >=4 times, saw {ref_count} — wiring incomplete.')

    with open(twb_path, 'w', encoding='utf-8') as f:
        f.write(wired)
    print(f"✓ Wired datasource '{caption}' ({connection_name}) with {len(fields)} field(s) into {twb_path}", file=sys.stderr)
    print(twb_path)


if __name__ == '__main__':
    main()
