"""
Regression coverage for wire_datasource.py, the Python port of wire-datasource.mjs.

Every scenario here was verified byte-for-byte (stdout, stderr, exit code, and
the resulting wired .twb XML) against the original Node script before the .mjs
was removed. These tests exercise the CLI contract directly (subprocess),
matching how SKILL.md invokes the script, and no longer depend on Node.
"""

import json
import os
import re
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'wire_datasource.py')

TWB_TEMPLATE = """<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1'>
  <datasources />
  <worksheets>
    <worksheet name='Sheet 1'>
      <table>
        <view>
          <datasources />
        </view>
      </table>
    </worksheet>
  </worksheets>
</workbook>
"""


def run_wire(twb_path, descriptor_path):
    return subprocess.run([sys.executable, SCRIPT, twb_path, descriptor_path], capture_output=True, text=True)


def write_descriptor(tmp_path, descriptor):
    path = tmp_path / 'descriptor.json'
    path.write_text(json.dumps(descriptor))
    return str(path)


def write_twb(tmp_path, content=TWB_TEMPLATE, filename='App.twb'):
    path = tmp_path / filename
    path.write_text(content)
    return str(path)


def descriptor_happy():
    return {
        "caption": "Superstore Datasource",
        "repositoryId": "SuperstoreDatasource",
        "site": "mcp-test",
        "server": "10ax.online.tableau.com",
        "connectionName": "sqlproxy.abc123",
        "fields": [
            {"name": "Profit", "datatype": "real", "role": "measure"},
            {"name": "Region", "datatype": "string", "role": "dimension"},
            {"name": "Order Date", "datatype": "date", "role": "dimension"},
            {"name": "Quantity", "datatype": "integer", "role": "measure"},
        ],
    }


def test_happy_path_wires_all_four_locations_with_matching_join_key(tmp_path):
    twb_path = write_twb(tmp_path)
    desc_path = write_descriptor(tmp_path, descriptor_happy())
    result = run_wire(twb_path, desc_path)

    assert result.returncode == 0
    assert result.stdout.strip() == twb_path
    assert "✓ Wired datasource 'Superstore Datasource' (sqlproxy.abc123) with 4 field(s)" in result.stderr

    wired = open(twb_path).read()
    assert '<datasources />' not in wired
    # join key appears exactly 4x: root name, root relation connection, view name, dependencies datasource
    assert wired.count("'sqlproxy.abc123'") == 4
    # real -> quantitative measure (Sum), string -> nominal dimension (Count),
    # date -> ordinal dimension, integer -> quantitative measure
    assert "<column aggregation='Sum' datatype='real' name='[Profit]' role='measure' type='quantitative' />" in wired
    assert "<column aggregation='Count' datatype='string' name='[Region]' role='dimension' type='nominal' />" in wired
    assert "<column aggregation='Count' datatype='date' name='[Order Date]' role='dimension' type='ordinal' />" in wired
    assert "<column aggregation='Sum' datatype='integer' name='[Quantity]' role='measure' type='quantitative' />" in wired
    assert "<column-instance column='[Profit]' derivation='Sum' name='[sum:Profit:qk]' pivot='key' type='quantitative' />" in wired
    assert "<column-instance column='[Region]' derivation='None' name='[none:Region:nk]' pivot='key' type='nominal' />" in wired


def test_spatial_field_aggregates_with_collect(tmp_path):
    descriptor = descriptor_happy()
    descriptor['fields'] = [{"name": "Geometry", "datatype": "spatial", "role": "dimension"}]
    twb_path = write_twb(tmp_path)
    desc_path = write_descriptor(tmp_path, descriptor)
    result = run_wire(twb_path, desc_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    # spatial field aggregates with Collect (derive_field's spatial branch), matching the embedded path
    assert "<column aggregation='Collect' datatype='spatial' name='[Geometry]' role='dimension' type='nominal' />" in wired


def test_missing_required_descriptor_field(tmp_path):
    descriptor = descriptor_happy()
    del descriptor['site']
    twb_path = write_twb(tmp_path)
    desc_path = write_descriptor(tmp_path, descriptor)
    result = run_wire(twb_path, desc_path)

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ Descriptor is missing required string "site".'


def test_empty_fields_array_is_rejected(tmp_path):
    descriptor = descriptor_happy()
    descriptor['fields'] = []
    twb_path = write_twb(tmp_path)
    desc_path = write_descriptor(tmp_path, descriptor)
    result = run_wire(twb_path, desc_path)

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ Descriptor "fields" must list at least one field the app will query.'


def test_field_missing_name_is_rejected(tmp_path):
    descriptor = descriptor_happy()
    descriptor['fields'] = [{"datatype": "real", "role": "measure"}]
    twb_path = write_twb(tmp_path)
    desc_path = write_descriptor(tmp_path, descriptor)
    result = run_wire(twb_path, desc_path)

    assert result.returncode == 1
    assert 'Every field needs a string "name" (field #0 was' in result.stderr


def test_connection_name_must_start_with_sqlproxy_prefix(tmp_path):
    descriptor = descriptor_happy()
    descriptor['connectionName'] = 'notsqlproxy.abc'
    twb_path = write_twb(tmp_path)
    desc_path = write_descriptor(tmp_path, descriptor)
    result = run_wire(twb_path, desc_path)

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ connectionName must start with "sqlproxy." (got "notsqlproxy.abc").'


def test_generated_connection_name_when_omitted(tmp_path):
    descriptor = descriptor_happy()
    del descriptor['connectionName']
    twb_path = write_twb(tmp_path)
    desc_path = write_descriptor(tmp_path, descriptor)
    result = run_wire(twb_path, desc_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    assert re.search(r"sqlproxy\.[a-z0-9]+", wired)


def test_missing_worksheets_element_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path, content='<workbook><datasources /></workbook>')
    desc_path = write_descriptor(tmp_path, descriptor_happy())
    result = run_wire(twb_path, desc_path)

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ No <worksheets> element found — is this a scaffolded data-app .twb?'


def test_root_anchor_already_wired_is_rejected(tmp_path):
    twb = TWB_TEMPLATE.replace(
        "  <datasources />\n", "  <datasources><datasource name='already' /></datasources>\n", 1
    )
    twb_path = write_twb(tmp_path, content=twb)
    desc_path = write_descriptor(tmp_path, descriptor_happy())
    result = run_wire(twb_path, desc_path)

    assert result.returncode == 1
    assert 'Root "<datasources />" anchor not found before <worksheets>' in result.stderr


def test_view_anchor_already_wired_is_rejected(tmp_path):
    # Fill only the second (view) anchor, leaving the root one empty.
    twb = TWB_TEMPLATE.replace("<datasources />", "<<<ANCHOR>>>")
    twb = twb.replace("<<<ANCHOR>>>", "<datasources />", 1)
    twb = twb.replace("<<<ANCHOR>>>", "<datasources><datasource name='already' /></datasources>")
    twb_path = write_twb(tmp_path, content=twb)
    desc_path = write_descriptor(tmp_path, descriptor_happy())
    result = run_wire(twb_path, desc_path)

    assert result.returncode == 1
    assert 'View "<datasources />" anchor not found inside <worksheets>' in result.stderr


def datasource(n, **overrides):
    ds = {
        "caption": f"DS {n}",
        "repositoryId": f"DS{n}",
        "site": "mcp-test",
        "server": "10ax.online.tableau.com",
        "connectionName": f"sqlproxy.ds{n}",
        "fields": [{"name": f"Field{n}", "datatype": "string", "role": "dimension"}],
    }
    ds.update(overrides)
    return ds


def view_of(wired):
    import xml.etree.ElementTree as ET
    root = ET.fromstring(wired)
    return root, root.find('./worksheets/worksheet/table/view')


def test_multiple_datasources_are_all_listed_on_the_host_sheet_primary_first(tmp_path):
    twb_path = write_twb(tmp_path)
    desc_path = write_descriptor(tmp_path, {"datasources": [datasource(n) for n in range(1, 6)]})
    result = run_wire(twb_path, desc_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == twb_path
    for n in range(1, 6):
        assert f"✓ Wired datasource 'DS {n}' (sqlproxy.ds{n}) with 1 field(s)" in result.stderr

    wired = open(twb_path).read()
    root, view = view_of(wired)
    names = [f'sqlproxy.ds{n}' for n in range(1, 6)]
    assert [d.get('name') for d in root.findall('./datasources/datasource')] == names
    assert [d.get('dbname') for d in root.findall('./datasources/datasource/connection')] == [f'DS{n}' for n in range(1, 6)]
    assert [d.get('name') for d in view.findall('./datasources/datasource')] == names
    # Only the primary carries datasource-dependencies.
    assert [d.get('datasource') for d in view.findall('./datasource-dependencies')] == ['sqlproxy.ds1']
    assert wired.count("'sqlproxy.ds1'") == 4
    for name in names[1:]:
        assert wired.count(f"'{name}'") == 3


def test_single_entry_datasources_list_matches_legacy_descriptor(tmp_path):
    legacy_dir = tmp_path / 'legacy'
    listed_dir = tmp_path / 'listed'
    legacy_dir.mkdir()
    listed_dir.mkdir()
    legacy_twb = write_twb(legacy_dir)
    listed_twb = write_twb(listed_dir)
    assert run_wire(legacy_twb, write_descriptor(legacy_dir, descriptor_happy())).returncode == 0
    assert run_wire(listed_twb, write_descriptor(listed_dir, {"datasources": [descriptor_happy()]})).returncode == 0
    assert open(legacy_twb).read() == open(listed_twb).read()


def test_generated_connection_names_are_distinct_across_datasources(tmp_path):
    entries = [datasource(n) for n in range(1, 9)]
    for entry in entries:
        del entry['connectionName']
    twb_path = write_twb(tmp_path)
    result = run_wire(twb_path, write_descriptor(tmp_path, {"datasources": entries}))

    assert result.returncode == 0, result.stderr
    root, view = view_of(open(twb_path).read())
    names = [d.get('name') for d in root.findall('./datasources/datasource')]
    assert len(set(names)) == 8
    assert all(name.startswith('sqlproxy.') for name in names)
    assert [d.get('name') for d in view.findall('./datasources/datasource')] == names


def test_empty_datasources_list_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    result = run_wire(twb_path, write_descriptor(tmp_path, {"datasources": []}))

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ Descriptor "datasources" must list at least one datasource.'
    assert open(twb_path).read() == TWB_TEMPLATE


def test_datasources_mixed_with_top_level_keys_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    descriptor = {"caption": "Orders", "datasources": [datasource(1)], "fields": []}
    result = run_wire(twb_path, write_descriptor(tmp_path, descriptor))

    assert result.returncode == 1
    assert result.stderr.strip() == (
        '✗ Descriptor mixes "datasources" with top-level "caption", "fields". '
        "Put every datasource's settings inside its datasources[] entry."
    )
    assert open(twb_path).read() == TWB_TEMPLATE


def test_invalid_entry_error_names_its_index(tmp_path):
    bad = datasource(2)
    del bad['site']
    twb_path = write_twb(tmp_path)
    result = run_wire(twb_path, write_descriptor(tmp_path, {"datasources": [datasource(1), bad]}))

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ datasources[1]: Descriptor is missing required string "site".'
    assert open(twb_path).read() == TWB_TEMPLATE


def test_duplicate_repository_id_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    before = open(twb_path).read()
    entries = [datasource(1), datasource(2, repositoryId='DS1')]
    result = run_wire(twb_path, write_descriptor(tmp_path, {"datasources": entries}))

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ datasources[1]: repositoryId "DS1" is listed more than once.'
    assert open(twb_path).read() == before


def test_duplicate_caption_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    before = open(twb_path).read()
    entries = [datasource(1, caption='Orders'), datasource(2, caption='Orders')]
    result = run_wire(twb_path, write_descriptor(tmp_path, {"datasources": entries}))

    assert result.returncode == 1
    assert result.stderr.strip() == (
        '✗ datasources[1]: caption "Orders" is already used by datasources[0]. '
        'Give each datasource a distinct caption (e.g. "Sales Orders" / "Finance Orders") so app.js can find it by name.'
    )
    assert open(twb_path).read() == before


def test_duplicate_connection_name_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    before = open(twb_path).read()
    entries = [datasource(1), datasource(2, connectionName='sqlproxy.ds1')]
    result = run_wire(twb_path, write_descriptor(tmp_path, {"datasources": entries}))

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ connectionName values must be unique across datasources.'
    assert open(twb_path).read() == before


def test_rewiring_an_already_wired_twb_says_how_to_recover(tmp_path):
    twb_path = write_twb(tmp_path)
    desc_path = write_descriptor(tmp_path, descriptor_happy())
    assert run_wire(twb_path, desc_path).returncode == 0
    wired = open(twb_path).read()

    result = run_wire(twb_path, desc_path)

    assert result.returncode == 1
    assert result.stderr.strip() == (
        '✗ This .twb is already wired. To change its datasources, re-scaffold, copy content/src/app.js '
        'into the new workspace, and wire every datasource in one run.'
    )
    assert open(twb_path).read() == wired


def test_explicit_and_generated_connection_names_mix(tmp_path):
    twb_path = write_twb(tmp_path)
    entries = [datasource(1), datasource(2, connectionName=None), datasource(3)]
    result = run_wire(twb_path, write_descriptor(tmp_path, {"datasources": entries}))

    assert result.returncode == 0, result.stderr
    _, view = view_of(open(twb_path).read())
    names = [d.get('name') for d in view.findall('./datasources/datasource')]
    assert names[0] == 'sqlproxy.ds1' and names[2] == 'sqlproxy.ds3'
    assert re.fullmatch(r'sqlproxy\.[a-z0-9]{22}', names[1])
    assert len(set(names)) == 3


def test_anchor_outside_the_view_is_rejected(tmp_path):
    # The first empty <datasources /> after <worksheets> isn't in a view, so the
    # datasources would be listed somewhere the server doesn't read.
    content = TWB_TEMPLATE.replace(
        "<worksheet name='Sheet 1'>\n      <table>\n        <view>\n          <datasources />\n        </view>",
        "<worksheet name='Sheet 1'>\n      <datasources />\n      <table>\n        <view>\n        </view>",
    )
    assert content != TWB_TEMPLATE
    twb_path = write_twb(tmp_path, content)
    result = run_wire(twb_path, write_descriptor(tmp_path, descriptor_happy()))

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ No worksheet view lists the primary datasource sqlproxy.abc123 — wiring incomplete.'
    assert open(twb_path).read() == content


def test_default_site_omits_site_path_and_attribute(tmp_path):
    descriptor = descriptor_happy()
    descriptor['site'] = ''
    twb_path = write_twb(tmp_path)
    result = run_wire(twb_path, write_descriptor(tmp_path, descriptor))

    assert result.returncode == 0, result.stderr
    wired = open(twb_path).read()
    assert "<repository-location id='SuperstoreDatasource' path='/datasources' revision='1.0' />" in wired
    assert 'site=' not in wired


XLS_PATH = 'Data/Datasources/Sample - Superstore.xls'


def add_data_file(tmp_path, rel=XLS_PATH, content=b'\xd0\xcf\x11\xe0'):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def excel_descriptor(**overrides):
    ds = {
        "type": "file",
        "caption": "Sample - Superstore",
        "file": XLS_PATH,
        "table": "Orders",
        "fields": [
            {"name": "Sales", "datatype": "real", "role": "measure"},
            {"name": "Region", "datatype": "string", "role": "dimension"},
            {"name": "Order Date", "datatype": "date", "role": "dimension"},
        ],
    }
    ds.update(overrides)
    return ds


def csv_descriptor(**overrides):
    ds = {
        "type": "file",
        "caption": "Orders CSV",
        "file": "Data/orders.csv",
        "fields": [
            {"name": "Profit", "datatype": "real", "role": "measure"},
            {"name": "Ship Date", "datatype": "date", "role": "dimension"},
        ],
    }
    ds.update(overrides)
    return ds


def test_excel_file_wires_federated_datasource_with_matching_join_keys(tmp_path):
    add_data_file(tmp_path)
    twb_path = write_twb(tmp_path)
    result = run_wire(twb_path, write_descriptor(tmp_path, excel_descriptor()))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == twb_path
    wired = open(twb_path).read()
    root, view = view_of(wired)
    root_ds = root.find('./datasources/datasource')
    name = root_ds.get('name')
    assert re.fullmatch(r'federated\.[a-z0-9]{22}', name)
    assert f"✓ Wired datasource 'Sample - Superstore' ({name}) with 3 field(s)" in result.stderr
    key = 'excel-direct.' + name.split('.', 1)[1]
    assert root_ds.get('caption') == 'Sample - Superstore'
    assert root_ds.find('./connection').get('class') == 'federated'
    named = root_ds.find('./connection/named-connections/named-connection')
    assert named.get('name') == key
    file_connection = named.find('./connection')
    assert file_connection.get('class') == 'excel-direct'
    assert file_connection.get('filename') == XLS_PATH
    relation = root_ds.find('./connection/relation')
    assert relation.attrib == {'connection': key, 'name': 'Orders', 'table': '[Orders$]', 'type': 'table'}
    records = {r.findtext('remote-name'): r for r in root_ds.iter('metadata-record')}
    assert records['Sales'].findtext('remote-type') == '5'
    assert records['Region'].findtext('remote-type') == '130'
    assert records['Order Date'].findtext('remote-type') == '7'
    assert {r.findtext('parent-name') for r in records.values()} == {'[Orders]'}
    assert 'sqlproxy' not in wired

    assert [d.get('name') for d in view.findall('./datasources/datasource')] == [name]
    assert [d.get('datasource') for d in view.findall('./datasource-dependencies')] == [name]
    assert "<column aggregation='Sum' datatype='real' name='[Sales]' role='measure' type='quantitative' />" in wired
    assert "<column-instance column='[Region]' derivation='None' name='[none:Region:nk]' pivot='key' type='nominal' />" in wired


def test_csv_file_splits_directory_and_filename(tmp_path):
    add_data_file(tmp_path, 'Data/orders.csv', b'Profit,Ship Date\n1.5,2026-01-31\n')
    twb_path = write_twb(tmp_path)
    result = run_wire(twb_path, write_descriptor(tmp_path, csv_descriptor()))

    assert result.returncode == 0, result.stderr
    root, _ = view_of(open(twb_path).read())
    root_ds = root.find('./datasources/datasource')
    named = root_ds.find('./connection/named-connections/named-connection')
    assert named.get('name') == 'textscan.' + root_ds.get('name').split('.', 1)[1]
    assert named.find('./connection').attrib == {
        'class': 'textscan', 'directory': 'Data', 'filename': 'orders.csv', 'password': '', 'server': ''}
    relation = root_ds.find('./connection/relation')
    assert relation.get('name') == 'orders.csv'
    assert relation.get('table') == '[orders#csv]'
    records = {r.findtext('remote-name'): r for r in root_ds.iter('metadata-record')}
    assert records['Profit'].findtext('remote-type') == '5'
    assert records['Ship Date'].findtext('remote-type') == '133'
    assert {r.findtext('parent-name') for r in records.values()} == {'[orders.csv]'}


def test_published_and_file_datasources_wire_in_one_run(tmp_path):
    add_data_file(tmp_path)
    twb_path = write_twb(tmp_path)
    descriptor = {"datasources": [descriptor_happy(), excel_descriptor()]}
    result = run_wire(twb_path, write_descriptor(tmp_path, descriptor))

    assert result.returncode == 0, result.stderr
    wired = open(twb_path).read()
    root, view = view_of(wired)
    names = [d.get('name') for d in root.findall('./datasources/datasource')]
    assert names[0] == 'sqlproxy.abc123' and names[1].startswith('federated.')
    assert [d.get('name') for d in view.findall('./datasources/datasource')] == names
    assert [d.get('datasource') for d in view.findall('./datasource-dependencies')] == ['sqlproxy.abc123']


def test_file_missing_from_the_workspace_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    result = run_wire(twb_path, write_descriptor(tmp_path, excel_descriptor()))

    assert result.returncode == 1
    assert result.stderr.strip() == (
        f"✗ Datasource 'Sample - Superstore' file \"{XLS_PATH}\" is not in the workspace ({tmp_path}). "
        'Copy it there first, at that path relative to the .twb.'
    )
    assert open(twb_path).read() == TWB_TEMPLATE


def test_file_outside_data_folder_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    for bad in ('orders.csv', 'Data/../orders.csv', '/abs/Data/orders.csv', 'Resources/orders.csv'):
        result = run_wire(twb_path, write_descriptor(tmp_path, csv_descriptor(file=bad)))
        assert result.returncode == 1
        assert '"file" must be a path inside the workspace Data/ folder' in result.stderr
    assert open(twb_path).read() == TWB_TEMPLATE


def test_unsupported_file_type_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    result = run_wire(twb_path, write_descriptor(tmp_path, csv_descriptor(file='Data/orders.json')))

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ "file" must be an Excel (.xls, .xlsx, .xlsm) or CSV (.csv) file (got "Data/orders.json").'


def test_excel_requires_a_table_and_csv_rejects_one(tmp_path):
    twb_path = write_twb(tmp_path)
    descriptor = excel_descriptor()
    del descriptor['table']
    result = run_wire(twb_path, write_descriptor(tmp_path, descriptor))
    assert result.returncode == 1
    assert result.stderr.strip() == '✗ Excel datasources need "table": the name of the sheet to query.'

    result = run_wire(twb_path, write_descriptor(tmp_path, csv_descriptor(table='orders')))
    assert result.returncode == 1
    assert result.stderr.strip() == '✗ "table" applies only to Excel files; a CSV file is its own table.'


def test_unknown_type_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    result = run_wire(twb_path, write_descriptor(tmp_path, excel_descriptor(type='extract')))

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ Descriptor "type" must be "published" or "file" (got "extract").'


def test_rewiring_a_file_wired_twb_is_rejected(tmp_path):
    add_data_file(tmp_path)
    twb_path = write_twb(tmp_path)
    desc_path = write_descriptor(tmp_path, excel_descriptor())
    assert run_wire(twb_path, desc_path).returncode == 0

    result = run_wire(twb_path, desc_path)

    assert result.returncode == 1
    assert '✗ This .twb is already wired.' in result.stderr


def test_wired_file_twb_packages_with_its_data(tmp_path):
    import zipfile
    workspace = tmp_path / 'Sales Demo'
    ext_dir = workspace / 'Packages' / 'com.tableau.mcp.sales-demo' / 'extensions'
    ext_dir.mkdir(parents=True)
    (ext_dir / 'data-app.trex').write_text('<manifest/>')
    add_data_file(workspace)
    add_data_file(workspace, 'Data/orders.csv', b'Profit,Ship Date\n')
    twb_path = write_twb(workspace, filename='Sales Demo.twb')
    descriptor = {"datasources": [excel_descriptor(), csv_descriptor()]}
    assert run_wire(twb_path, write_descriptor(tmp_path, descriptor)).returncode == 0

    package = os.path.join(os.path.dirname(SCRIPT), 'package_twbx.py')
    result = subprocess.run([sys.executable, package, str(workspace)], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    with zipfile.ZipFile(result.stdout.strip()) as archive:
        entries = archive.namelist()
    assert XLS_PATH in entries
    assert 'Data/orders.csv' in entries
