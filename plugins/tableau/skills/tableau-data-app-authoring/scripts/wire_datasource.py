#!/usr/bin/env python3
"""
Wire one or more published datasources into a scaffolded data-app `.twb`.

`scaffold-data-app` emits a workbook with TWO empty `<datasources />` anchors
(workbook root + worksheet `<view>`). Until both are filled the extension's
`getAllDataSourcesAsync()` finds nothing and renders "no data source found in
the workbook." This fills both with N published `sqlproxy` (Data Server)
datasources, keeping each `sqlproxy.<hash>` join key byte-identical everywhere.

A script, not freehand XML, because the wiring spans coordinated locations that
must agree exactly (root datasource `name`, root `relation connection`, view
`datasource name`, and for the primary `datasource-dependencies datasource`);
miss one and the workbook silently reaches no data.

Every datasource is listed on the extension's host sheet `<view>`: the server
only connects and keeps datasources listed there, so one listed only elsewhere
fails at query time. The first datasource is the primary (it alone gets
`datasource-dependencies`); the app finds the rest by caption via
`getAllDataSourcesAsync()`.

Usage: python3 wire_datasource.py <path-to.twb> <descriptor.json>

descriptor.json (Claude assembles from list-datasources + get-datasource-metadata;
list ONLY the fields the app will query). Either one datasource:
  {
    "caption":      "Superstore Datasource",
    "repositoryId": "SuperstoreDatasource",   // published DS contentUrl (== repo-location id / dbname)
    "site":         "mcp-test",                // "" for the Default site
    "server":       "10ax.online.tableau.com",
    "channel":      "https",   // optional, default https
    "port":         443,       // optional, default 443 (use http/80 for on-prem)
    "connectionName": "sqlproxy.<hash>",  // optional, generated if omitted
    "fields": [
      { "name": "Profit", "datatype": "real",   "role": "measure"   },
      { "name": "Region", "datatype": "string", "role": "dimension" }
    ]
  }
or any number of them, primary first, wired in a single run:
  { "datasources": [ { ...as above... }, { ...as above... } ] }
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
def derive_field(field, ordinal, error_prefix=''):
    name = field.get('name') if isinstance(field, dict) else None
    if not name or not isinstance(name, str):
        die(f'{error_prefix}Every field needs a string "name" (field #{ordinal} was {json.dumps(field, separators=(",", ":"))}).')
    datatype = str(field.get('datatype') or 'string').lower()
    role = 'measure' if field.get('role') == 'measure' else 'dimension'
    is_measure = role == 'measure'
    field_type = type_of(datatype)
    # Spatial fields aggregate with Collect (a geometry union), not Sum/Count.
    aggregation = 'Collect' if datatype == 'spatial' else ('Sum' if is_measure else 'Count')
    return {
        'name': name,
        'datatype': datatype,
        'role': role,
        'type': field_type,
        'ordinal': ordinal,
        'aggregation': aggregation,
        # role attribute: 0 = dimension, 1 = measure
        'roleAttr': 1 if is_measure else 0,
        'localName': f'[{name}]',
        # column-instance derivation + name token: [sum:Profit:qk] / [none:Region:nk]
        'derivation': 'Sum' if is_measure else 'None',
        'instanceName': f'[sum:{name}:qk]' if is_measure else f'[none:{name}:nk]',
    }


# Desktop-style internal datasource name (`sqlproxy.` + 22 random chars). It's the join key
# repeated across the four wiring locations, so it only needs to be unique within the workbook.
def generate_connection_name():
    token = lambda: ''.join(random.choices(string.ascii_lowercase + string.digits, k=11))
    return f'sqlproxy.{token()}{token()}'


# Validate one datasource descriptor. `error_prefix` names the datasource in errors when wiring several.
def parse_datasource(descriptor, error_prefix=''):
    if not isinstance(descriptor, dict):
        die(f'{error_prefix}Descriptor must be a JSON object.')
    for key in ('caption', 'repositoryId', 'site', 'server'):
        value = descriptor.get(key)
        # site may be "" (the Default site); everything else must be non-empty.
        if not isinstance(value, str) or (not value and key != 'site'):
            die(f'{error_prefix}Descriptor is missing required string "{key}".')
    channel = descriptor.get('channel') or 'https'
    port = descriptor.get('port') if descriptor.get('port') is not None else (443 if channel == 'https' else 80)

    fields_in = descriptor.get('fields') if isinstance(descriptor.get('fields'), list) else []
    if len(fields_in) == 0:
        die(f'{error_prefix}Descriptor "fields" must list at least one field the app will query.')

    connection_name = descriptor.get('connectionName')
    if connection_name and not connection_name.startswith('sqlproxy.'):
        die(f'{error_prefix}connectionName must start with "sqlproxy." (got "{connection_name}").')

    return {
        'caption': descriptor['caption'],
        'repositoryId': descriptor['repositoryId'],
        'site': descriptor['site'],
        'server': descriptor['server'],
        'channel': channel,
        'port': port,
        'fields': [derive_field(f, i, error_prefix) for i, f in enumerate(fields_in)],
        'connectionName': connection_name,
    }


def parse_descriptor(descriptor):
    if isinstance(descriptor, dict) and 'datasources' in descriptor:
        entries = descriptor['datasources']
        if not isinstance(entries, list) or len(entries) == 0:
            die('Descriptor "datasources" must list at least one datasource.')
        datasources = [parse_datasource(d, f'datasources[{i}]: ') for i, d in enumerate(entries)]
    else:
        datasources = [parse_datasource(descriptor)]

    seen_repository_ids = set()
    for i, ds in enumerate(datasources):
        if ds['repositoryId'] in seen_repository_ids:
            die(f'datasources[{i}]: repositoryId "{ds["repositoryId"]}" is listed more than once.')
        seen_repository_ids.add(ds['repositoryId'])

    # Single source of truth for each join key; they must be distinct across datasources.
    explicit_names = [ds['connectionName'] for ds in datasources if ds['connectionName']]
    if len(set(explicit_names)) != len(explicit_names):
        die('connectionName values must be unique across datasources.')
    used = set(explicit_names)
    for ds in datasources:
        if not ds['connectionName']:
            name = generate_connection_name()
            while name in used:
                name = generate_connection_name()
            ds['connectionName'] = name
            used.add(name)
    return datasources


# The Default site has no /t/<site> path segment and no site attribute.
def repository_location_xml(repository_id, site):
    if not site:
        return f"<repository-location id='{esc(repository_id)}' path='/datasources' revision='1.0' />"
    return f"<repository-location id='{esc(repository_id)}' path='/t/{esc(site)}/datasources' revision='1.0' site='{esc(site)}' />"


def root_datasource_xml(ds):
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
        for f in ds['fields']
    )
    return f"""    <datasource caption='{esc(ds['caption'])}' inline='true' name='{esc(ds['connectionName'])}' version='18.1'>
      {repository_location_xml(ds['repositoryId'], ds['site'])}
      <connection channel='{esc(ds['channel'])}' class='sqlproxy' dbname='{esc(ds['repositoryId'])}' directory='dataserver' port='{esc(ds['port'])}' server='{esc(ds['server'])}' server-ds-friendly-name='{esc(ds['caption'])}' username=''>
        <relation type='collection'>
          <relation connection='{esc(ds['connectionName'])}' name='sqlproxy' table='[sqlproxy]' type='table' />
        </relation>
        <metadata-records>
{metadata_records}
        </metadata-records>
      </connection>
    </datasource>"""


def view_dependencies_xml(ds):
    view_columns = '\n'.join(
        f"            <column aggregation='{f['aggregation']}' datatype='{esc(f['datatype'])}' name='{esc(f['localName'])}' role='{f['role']}' type='{f['type']}' />"
        for f in ds['fields']
    )
    view_column_instances = '\n'.join(
        f"            <column-instance column='{esc(f['localName'])}' derivation='{f['derivation']}' name='{esc(f['instanceName'])}' pivot='key' type='{f['type']}' />"
        for f in ds['fields']
    )
    return f"""          <datasource-dependencies datasource='{esc(ds['connectionName'])}'>
{view_columns}
{view_column_instances}
          </datasource-dependencies>"""


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

    datasources = parse_descriptor(descriptor)
    primary = datasources[0]

    # --- build the XML blocks ----------------------------------------------

    root_datasources = '<datasources>\n' + '\n'.join(root_datasource_xml(ds) for ds in datasources) + '\n  </datasources>'

    view_entries = '\n'.join(
        f"            <datasource caption='{esc(ds['caption'])}' name='{esc(ds['connectionName'])}' />"
        for ds in datasources
    )
    view_datasources = f"""<datasources>
{view_entries}
          </datasources>
{view_dependencies_xml(primary)}"""

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
    head = head.replace(EMPTY_ANCHOR, root_datasources, 1)

    # View anchor is the first empty <datasources /> inside the worksheets section.
    if EMPTY_ANCHOR not in tail:
        die(f'View "{EMPTY_ANCHOR}" anchor not found inside <worksheets> — already wired or template drifted.')
    tail = tail.replace(EMPTY_ANCHOR, view_datasources, 1)

    wired = head + tail

    # --- verify before writing ----------------------------------------------

    if EMPTY_ANCHOR in wired:
        die('An empty <datasources /> anchor survived wiring — refusing to write a half-wired workbook.')
    # Each join key appears in the root datasource name, root relation connection,
    # and view datasource name; the primary's also in datasource-dependencies.
    for ds in datasources:
        expected = 4 if ds is primary else 3
        ref_count = wired.count(f"'{ds['connectionName']}'")
        if ref_count < expected:
            die(f"Expected connection name {ds['connectionName']} to appear >={expected} times, saw {ref_count} — wiring incomplete.")

    with open(twb_path, 'w', encoding='utf-8') as f:
        f.write(wired)
    for ds in datasources:
        print(f"✓ Wired datasource '{ds['caption']}' ({ds['connectionName']}) with {len(ds['fields'])} field(s) into {twb_path}", file=sys.stderr)
    print(twb_path)


if __name__ == '__main__':
    main()
