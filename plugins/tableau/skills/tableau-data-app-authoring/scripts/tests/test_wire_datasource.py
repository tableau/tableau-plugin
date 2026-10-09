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
