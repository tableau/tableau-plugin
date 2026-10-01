"""
Regression coverage for wire_embedded_datasource.py's CSV/textscan connector
— the original embedded-datasource path, validated byte-for-byte (stdout,
stderr, exit code, the resulting wired .twb XML, and the copied file) against
the original Node script before the .mjs was removed. These tests exercise
the CLI contract directly (subprocess), matching how SKILL.md invokes the
script.

NOTE: this pytest suite only proves the XML-splicing contract (what XML the
script writes into the .twb). End-to-end validation — scaffold -> wire ->
package -> publish -> query-datasource against a real Tableau site — is
manual / MCP-tool-driven and is NOT covered here.
"""

import re

from helpers import run_wire, write_csv, write_descriptor, write_twb

CSV_HAPPY = "full_name,country,titles,turned_pro\nRoger,Switzerland,20,1998\nRafael,Spain,22,2001\n"


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


def test_csv_shape_unaffected_by_refactor(tmp_path):
    # regression guard: .csv still produces CSV's original remote-type / parent-name /
    # textscan-relation shape after the connector-registry refactor.
    twb_path = write_twb(tmp_path)
    csv_path = write_csv(tmp_path, CSV_HAPPY)
    desc_path = write_descriptor(tmp_path, {"connectionName": "federated.abc123"})
    result = run_wire(twb_path, csv_path, desc_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    # CSV parent-name = [<filename>], remote-type 129 (string) / 5 (quantitative)
    assert '<parent-name>[players.csv]</parent-name>' in wired
    assert '<remote-type>129</remote-type>' in wired
    assert '<remote-type>5</remote-type>' in wired
    # CSV textscan relation with #csv table suffix and root <column> overrides retained
    assert "<connection class='textscan' directory='Data' filename='players.csv' password='' server='' />" in wired
    assert "table='[players#csv]'" in wired
    assert "<column datatype='integer' name='[titles]' role='measure' type='quantitative' />" in wired
