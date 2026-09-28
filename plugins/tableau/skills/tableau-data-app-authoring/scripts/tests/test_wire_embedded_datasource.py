"""
Regression coverage for wire_embedded_datasource.py, the Python port of
wire-embedded-datasource.mjs.

Every scenario here was verified byte-for-byte (stdout, stderr, exit code, the
resulting wired .twb XML, and the copied CSV) against the original Node script
before the .mjs was removed. These tests exercise the CLI contract directly
(subprocess), matching how SKILL.md invokes the script, and no longer depend
on Node.
"""

import json
import os
import re
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'wire_embedded_datasource.py')

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

CSV_HAPPY = "full_name,country,titles,turned_pro\nRoger,Switzerland,20,1998\nRafael,Spain,22,2001\n"


def run_wire(twb_path, csv_path, descriptor_path=None):
    args = [sys.executable, SCRIPT, twb_path, csv_path]
    if descriptor_path:
        args.append(descriptor_path)
    return subprocess.run(args, capture_output=True, text=True)


def write_twb(tmp_path, content=TWB_TEMPLATE, filename='App.twb'):
    path = tmp_path / filename
    path.write_text(content)
    return str(path)


def write_csv(tmp_path, content, filename='players.csv'):
    path = tmp_path / filename
    path.write_text(content)
    return str(path)


def write_descriptor(tmp_path, descriptor):
    path = tmp_path / 'descriptor.json'
    path.write_text(json.dumps(descriptor))
    return str(path)


def test_happy_path_infers_types_and_copies_csv(tmp_path):
    twb_path = write_twb(tmp_path)
    csv_path = write_csv(tmp_path, CSV_HAPPY)
    desc_path = write_descriptor(tmp_path, {"connectionName": "federated.abc123"})
    result = run_wire(twb_path, csv_path, desc_path)

    assert result.returncode == 0
    assert result.stdout.strip() == twb_path
    assert "✓ Wired embedded CSV datasource 'Players' (federated.abc123) with 4 field(s)" in result.stderr
    assert f'✓ Copied players.csv to {tmp_path / "Data" / "players.csv"}' in result.stderr

    copied = tmp_path / 'Data' / 'players.csv'
    assert copied.read_text() == CSV_HAPPY

    wired = open(twb_path).read()
    assert '<datasources />' not in wired
    assert wired.count("'federated.abc123'") == 3
    assert wired.count("'textscan.abc123'") == 2
    # full_name/country -> string dimension; titles/turned_pro -> integer measure (default role from datatype)
    assert "<column datatype='string' name='[full_name]' role='dimension' type='nominal' />" in wired
    assert "<column datatype='integer' name='[titles]' role='measure' type='quantitative' />" in wired
    assert "<column datatype='integer' name='[turned_pro]' role='measure' type='quantitative' />" in wired
    assert "<column-instance column='[titles]' derivation='Sum' name='[sum:titles:qk]' pivot='key' type='quantitative' />" in wired


def test_descriptor_overrides_inferred_role(tmp_path):
    twb_path = write_twb(tmp_path)
    csv_path = write_csv(tmp_path, CSV_HAPPY)
    desc_path = write_descriptor(tmp_path, {
        "connectionName": "federated.abc123",
        "fields": [{"name": "turned_pro", "role": "dimension"}],
    })
    result = run_wire(twb_path, csv_path, desc_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    # datatype stays integer (inferred, not overridden) but role flips to dimension -> Count/None
    assert "<column datatype='integer' name='[turned_pro]' role='dimension' type='quantitative' />" in wired
    assert "<column-instance column='[turned_pro]' derivation='None' name='[none:turned_pro:nk]' pivot='key' type='quantitative' />" in wired


def test_caption_defaults_from_filename(tmp_path):
    twb_path = write_twb(tmp_path)
    csv_path = write_csv(tmp_path, CSV_HAPPY, filename='top_tennis-players.csv')
    result = run_wire(twb_path, csv_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    assert "caption='Top Tennis Players'" in wired


def test_non_csv_extension_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    csv_path = write_csv(tmp_path, "a,b\n1,2\n", filename='players.txt')
    result = run_wire(twb_path, csv_path)

    assert result.returncode == 1
    assert 'Only .csv files are supported' in result.stderr


def test_missing_csv_file_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    missing_csv = str(tmp_path / 'missing.csv')
    result = run_wire(twb_path, missing_csv)

    assert result.returncode == 1
    assert result.stderr.strip() == f'✗ CSV not found at {missing_csv}'


def test_header_only_csv_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    csv_path = write_csv(tmp_path, "full_name,country\n")
    result = run_wire(twb_path, csv_path)

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ CSV must have a header row plus at least one data row.'


def test_empty_header_column_name_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    csv_path = write_csv(tmp_path, "full_name,,country\nRoger,x,Switzerland\n")
    result = run_wire(twb_path, csv_path)

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ CSV header has an empty column name at position 1.'


def test_duplicate_header_column_name_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    csv_path = write_csv(tmp_path, "full_name,full_name\nRoger,Federer\n")
    result = run_wire(twb_path, csv_path)

    assert result.returncode == 1
    assert 'CSV header has a duplicate column name "full_name" at position 1' in result.stderr


def test_generated_connection_name_when_omitted(tmp_path):
    twb_path = write_twb(tmp_path)
    csv_path = write_csv(tmp_path, CSV_HAPPY)
    result = run_wire(twb_path, csv_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    assert re.search(r"federated\.[a-z0-9]+", wired)


def test_connection_name_must_start_with_federated_prefix(tmp_path):
    twb_path = write_twb(tmp_path)
    csv_path = write_csv(tmp_path, CSV_HAPPY)
    desc_path = write_descriptor(tmp_path, {"connectionName": "sqlproxy.wrong"})
    result = run_wire(twb_path, csv_path, desc_path)

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ connectionName must start with "federated." (got "sqlproxy.wrong").'
