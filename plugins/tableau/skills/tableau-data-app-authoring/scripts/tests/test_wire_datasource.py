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
