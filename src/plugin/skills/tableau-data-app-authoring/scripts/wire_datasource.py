#!/usr/bin/env python3
"""
Wire one or more datasources into a scaffolded data-app `.twb`: published ones
and files embedded in the workspace's `Data/` folder, in any mix.

`scaffold-data-app` emits a workbook with TWO empty `<datasources />` anchors
(workbook root + worksheet `<view>`). Until both are filled the extension's
`getAllDataSourcesAsync()` finds nothing and renders "no data source found in
the workbook." This fills both in one run with N datasources:
  - published: a `sqlproxy` (Data Server) connection, joined by `sqlproxy.<hash>`.
  - file: a `federated` datasource over one Excel sheet (`excel-direct`) or CSV
    file (`textscan`) at a workspace-relative `Data/...` path, joined by
    `federated.<hash>`; its named connection is `<class>.<hash>` (same hash).
Each join key stays byte-identical everywhere it appears.

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
or an embedded file (the file must already be in the workspace):
  {
    "type":     "file",
    "caption":  "Sample - Superstore",
    "file":     "Data/Datasources/Sample - Superstore.xls",  // relative to the .twb; .xls, .xlsx, .xlsm, or .csv
    "table":    "Orders",                                    // Excel only: the sheet to query
    "connectionName": "federated.<hash>",                    // optional, generated if omitted
    "fields": [ ...as above... ]
  }
or any number of either, primary first, wired in a single run:
  { "datasources": [ { ...as above... }, { ...as above... } ] }
`type` defaults to "published".
"""

import json
import os
import random
import re
import string
import sys
import xml.etree.ElementTree as ET

# The exact empty anchor emitted by the scaffold template. Matched literally.
EMPTY_ANCHOR = '<datasources />'

# Embedded file extension -> connection class.
FILE_CLASSES = {'.xls': 'excel-direct', '.xlsx': 'excel-direct', '.xlsm': 'excel-direct', '.csv': 'textscan'}

# local-type -> the remote-type code Tableau records for each file class.
FILE_REMOTE_TYPES = {
    'excel-direct': {'string': 130, 'integer': 20, 'real': 5, 'date': 7, 'datetime': 7, 'boolean': 11},
    'textscan': {'string': 129, 'integer': 20, 'real': 5, 'date': 133, 'datetime': 135, 'boolean': 11},
}


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
        'localName': bracket(name),
        # column-instance derivation + name token: [sum:Profit:qk] / [none:Region:nk]
        'derivation': 'Sum' if is_measure else 'None',
        'instanceName': bracket(f'sum:{name}:qk' if is_measure else f'none:{name}:nk'),
    }


# The hash after the prefix is letters and digits, as Tableau generates it.
def check_connection_hash(connection_name, error_prefix):
    if connection_name and not re.fullmatch(r'[a-z]+\.[A-Za-z0-9]+', connection_name):
        die(f'{error_prefix}connectionName must be letters and digits after the prefix (got "{connection_name}").')


def generate_connection_name(prefix):
    token = lambda: ''.join(random.choices(string.ascii_lowercase + string.digits, k=11))
    return f'{prefix}.{token()}{token()}'


def parse_fields(descriptor, error_prefix):
    fields_in = descriptor.get('fields') if isinstance(descriptor.get('fields'), list) else []
    if len(fields_in) == 0:
        die(f'{error_prefix}Descriptor "fields" must list at least one field the app will query.')
    return [derive_field(f, i, error_prefix) for i, f in enumerate(fields_in)]


# Validate one datasource descriptor. `error_prefix` names the datasource in errors when wiring several.
def parse_datasource(descriptor, error_prefix=''):
    if not isinstance(descriptor, dict):
        die(f'{error_prefix}Descriptor must be a JSON object.')
    kind = descriptor.get('type', 'published')
    if kind == 'file':
        return parse_file_datasource(descriptor, error_prefix)
    if kind != 'published':
        die(f'{error_prefix}Descriptor "type" must be "published" or "file" (got {json.dumps(kind)}).')
    for key in ('caption', 'repositoryId', 'site', 'server'):
        value = descriptor.get(key)
        # site may be "" (the Default site); everything else must be non-empty.
        if not isinstance(value, str) or (not value and key != 'site'):
            die(f'{error_prefix}Descriptor is missing required string "{key}".')
    channel = descriptor.get('channel') or 'https'
    port = descriptor.get('port') if descriptor.get('port') is not None else (443 if channel == 'https' else 80)

    fields = parse_fields(descriptor, error_prefix)

    connection_name = descriptor.get('connectionName')
    if connection_name and not connection_name.startswith('sqlproxy.'):
        die(f'{error_prefix}connectionName must start with "sqlproxy." (got "{connection_name}").')
    check_connection_hash(connection_name, error_prefix)

    return {
        'type': 'published',
        'caption': descriptor['caption'],
        'repositoryId': descriptor['repositoryId'],
        'site': descriptor['site'],
        'server': descriptor['server'],
        'channel': channel,
        'port': port,
        'fields': fields,
        'connectionName': connection_name,
    }


def parse_file_datasource(descriptor, error_prefix):
    for key in ('caption', 'file'):
        value = descriptor.get(key)
        if not isinstance(value, str) or not value:
            die(f'{error_prefix}Descriptor is missing required string "{key}".')
    file_path = descriptor['file'].replace('\\', '/')
    parts = file_path.split('/')
    if len(parts) < 2 or parts[0] != 'Data' or any(part in ('', '.', '..') for part in parts):
        die(f'{error_prefix}"file" must be a path inside the workspace Data/ folder, '
            f'e.g. "Data/Datasources/Sales.xlsx" (got "{descriptor["file"]}").')
    file_class = FILE_CLASSES.get(os.path.splitext(file_path)[1].lower())
    if not file_class:
        die(f'{error_prefix}"file" must be an Excel (.xls, .xlsx, .xlsm) or CSV (.csv) file (got "{file_path}").')

    table = descriptor.get('table')
    if file_class == 'excel-direct':
        if not isinstance(table, str) or not table:
            die(f'{error_prefix}Excel datasources need "table": the name of the sheet to query.')
    elif table is not None:
        die(f'{error_prefix}"table" applies only to Excel files; a CSV file is its own table.')

    fields = parse_fields(descriptor, error_prefix)

    connection_name = descriptor.get('connectionName')
    if connection_name and not connection_name.startswith('federated.'):
        die(f'{error_prefix}connectionName for a file datasource must start with "federated." (got "{connection_name}").')
    check_connection_hash(connection_name, error_prefix)

    return {
        'type': 'file',
        'caption': descriptor['caption'],
        'file': file_path,
        'class': file_class,
        'table': table,
        'fields': fields,
        'connectionName': connection_name,
    }


def parse_descriptor(descriptor):
    if isinstance(descriptor, dict) and 'datasources' in descriptor:
        extra_keys = [key for key in descriptor if key != 'datasources']
        if extra_keys:
            die(f'Descriptor mixes "datasources" with top-level {", ".join(json.dumps(k) for k in extra_keys)}. '
                'Put every datasource\'s settings inside its datasources[] entry.')
        entries = descriptor['datasources']
        if not isinstance(entries, list) or len(entries) == 0:
            die('Descriptor "datasources" must list at least one datasource.')
        datasources = [parse_datasource(d, f'datasources[{i}]: ') for i, d in enumerate(entries)]
    else:
        datasources = [parse_datasource(descriptor)]

    seen_repository_ids = set()
    for i, ds in enumerate(datasources):
        if ds['type'] != 'published':
            continue
        if ds['repositoryId'] in seen_repository_ids:
            die(f'datasources[{i}]: repositoryId "{ds["repositoryId"]}" is listed more than once.')
        seen_repository_ids.add(ds['repositoryId'])

    # app.js finds each datasource by caption, so captions must be distinct.
    caption_owner = {}
    for i, ds in enumerate(datasources):
        if ds['caption'] in caption_owner:
            die(f'datasources[{i}]: caption "{ds["caption"]}" is already used by datasources[{caption_owner[ds["caption"]]}]. '
                'Give each datasource a distinct caption (e.g. "Sales Orders" / "Finance Orders") so app.js can find it by name.')
        caption_owner[ds['caption']] = i

    # Single source of truth for each join key; they must be distinct across datasources.
    explicit_names = [ds['connectionName'] for ds in datasources if ds['connectionName']]
    if len(set(explicit_names)) != len(explicit_names):
        die('connectionName values must be unique across datasources.')
    used = set(explicit_names)
    for ds in datasources:
        if not ds['connectionName']:
            prefix = 'sqlproxy' if ds['type'] == 'published' else 'federated'
            name = generate_connection_name(prefix)
            while name in used:
                name = generate_connection_name(prefix)
            ds['connectionName'] = name
            used.add(name)
        # The connection the root relation points at: itself for sqlproxy, the
        # named file connection (same hash) for federated.
        if ds['type'] == 'published':
            ds['relationConnection'] = ds['connectionName']
        else:
            ds['relationConnection'] = f"{ds['class']}.{ds['connectionName'].split('.', 1)[1]}"
    return datasources


# The Default site has no /t/<site> path segment and no site attribute.
def repository_location_xml(repository_id, site):
    if not site:
        return f"<repository-location id='{esc(repository_id)}' path='/datasources' revision='1.0' />"
    return f"<repository-location id='{esc(repository_id)}' path='/t/{esc(site)}/datasources' revision='1.0' site='{esc(site)}' />"


def root_datasource_xml(ds):
    return published_datasource_xml(ds) if ds['type'] == 'published' else file_datasource_xml(ds)


# Tableau bracket-quotes table names, doubling any `]` inside.
def bracket(name):
    return '[' + name.replace(']', ']]') + ']'


def file_datasource_xml(ds):
    if ds['class'] == 'excel-direct':
        # A sheet named Orders is the table [Orders$].
        relation_name, table = ds['table'], bracket(f"{ds['table']}$")
        connection = (f"<connection class='excel-direct' cleaning='no' compat='no' dataRefreshTime='' "
                      f"filename='{esc(ds['file'])}' interpretationMode='0' password='' server='' validate='no' />")
    else:
        # CSV splits the path, and orders.csv is the table [orders#csv].
        directory, filename = ds['file'].rsplit('/', 1)
        stem, extension = filename.rsplit('.', 1)
        relation_name, table = filename, bracket(f'{stem}#{extension}')
        connection = (f"<connection class='textscan' directory='{esc(directory)}' "
                      f"filename='{esc(filename)}' password='' server='' />")
    remote_types = FILE_REMOTE_TYPES[ds['class']]
    metadata_records = '\n'.join(
        f"""          <metadata-record class='column'>
            <remote-name>{esc(f['name'])}</remote-name>
            <remote-type>{remote_types.get(f['datatype'], remote_types['string'])}</remote-type>
            <local-name>{esc(f['localName'])}</local-name>
            <parent-name>{esc(bracket(relation_name))}</parent-name>
            <remote-alias>{esc(f['name'])}</remote-alias>
            <ordinal>{f['ordinal']}</ordinal>
            <local-type>{esc(f['datatype'])}</local-type>
            <aggregation>{f['aggregation']}</aggregation>
            <contains-null>true</contains-null>
          </metadata-record>"""
        for f in ds['fields']
    )
    return f"""    <datasource caption='{esc(ds['caption'])}' inline='true' name='{esc(ds['connectionName'])}' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='{esc(ds['caption'])}' name='{esc(ds['relationConnection'])}'>
            {connection}
          </named-connection>
        </named-connections>
        <relation connection='{esc(ds['relationConnection'])}' name='{esc(relation_name)}' table='{esc(table)}' type='table' />
        <metadata-records>
{metadata_records}
        </metadata-records>
      </connection>
    </datasource>"""


def published_datasource_xml(ds):
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


# Check each join key sits where the server reads it, not just that it appears often enough.
def verify_wiring(wired, datasources):
    try:
        root = ET.fromstring(wired)
    except ET.ParseError as error:
        die(f'Wired .twb is not valid XML ({error}) — refusing to write it.')
    primary_name = datasources[0]['connectionName']

    root_datasources = {d.get('name'): d for d in root.findall('./datasources/datasource')}
    for ds in datasources:
        name = ds['connectionName']
        root_ds = root_datasources.get(name)
        if root_ds is None:
            die(f'Root <datasources> is missing {name} — wiring incomplete.')
        relation_connection = ds['relationConnection']
        if not any(r.get('connection') == relation_connection for r in root_ds.iter('relation')):
            target = 'itself' if relation_connection == name else relation_connection
            die(f'Root datasource {name} has no relation connection to {target} — wiring incomplete.')
        if ds['type'] == 'file' and not any(
                c.get('name') == relation_connection for c in root_ds.iter('named-connection')):
            die(f'Root datasource {name} has no named connection {relation_connection} — wiring incomplete.')

    # The server only connects datasources listed on the host sheet's view.
    host_view = next(
        (v for v in root.iter('view')
         if any(d.get('name') == primary_name for d in v.findall('./datasources/datasource'))),
        None,
    )
    if host_view is None:
        die(f'No worksheet view lists the primary datasource {primary_name} — wiring incomplete.')
    listed = {d.get('name') for d in host_view.findall('./datasources/datasource')}
    missing = [ds['connectionName'] for ds in datasources if ds['connectionName'] not in listed]
    if missing:
        die(f'Host sheet view does not list {", ".join(missing)} — the server would not connect them.')
    if host_view.find(f"./datasource-dependencies[@datasource='{primary_name}']") is None:
        die(f'Host sheet view has no datasource-dependencies for the primary {primary_name} — wiring incomplete.')


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

    # An embedded file the .twb points at must already sit in the workspace, or
    # the app packages and publishes but has no data at runtime.
    workspace = os.path.dirname(twb_path)
    for ds in datasources:
        if ds['type'] == 'file' and not os.path.isfile(os.path.join(workspace, ds['file'])):
            die(f"Datasource '{ds['caption']}' file \"{ds['file']}\" is not in the workspace ({workspace}). "
                'Copy it there first, at that path relative to the .twb.')

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

    if "class='sqlproxy'" in head or "class='federated'" in head:
        die('This .twb is already wired. To change its datasources, re-scaffold, copy content/src/app.js '
            'into the new workspace, and wire every datasource in one run.')

    # Root anchor lives in the head (before <worksheets>).
    if EMPTY_ANCHOR not in head:
        die(f'Root "{EMPTY_ANCHOR}" anchor not found before <worksheets> — template drifted.')
    head = head.replace(EMPTY_ANCHOR, root_datasources, 1)

    # View anchor is the first empty <datasources /> inside the worksheets section.
    if EMPTY_ANCHOR not in tail:
        die(f'View "{EMPTY_ANCHOR}" anchor not found inside <worksheets> — template drifted.')
    tail = tail.replace(EMPTY_ANCHOR, view_datasources, 1)

    wired = head + tail

    # --- verify before writing ----------------------------------------------

    if EMPTY_ANCHOR in wired:
        die('An empty <datasources /> anchor survived wiring — refusing to write a half-wired workbook.')
    verify_wiring(wired, datasources)

    with open(twb_path, 'w', encoding='utf-8') as f:
        f.write(wired)
    for ds in datasources:
        print(f"✓ Wired datasource '{ds['caption']}' ({ds['connectionName']}) with {len(ds['fields'])} field(s) into {twb_path}", file=sys.stderr)
    print(twb_path)


if __name__ == '__main__':
    main()
