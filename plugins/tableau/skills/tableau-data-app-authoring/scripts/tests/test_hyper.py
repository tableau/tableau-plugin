"""
Regression coverage for wire_embedded_datasource.py's Hyper connector.

.hyper is wiring-only: the script cannot introspect a proprietary binary
extract, so the caller must supply a descriptor.json with a non-empty
'fields' list. These tests write a dummy .hyper (never read) and drive the
descriptor-only path.

NOTE: this pytest suite only proves the XML-splicing contract (what XML the
script writes into the .twb). End-to-end validation — scaffold -> wire ->
package -> publish -> query-datasource against a real Tableau site — is
manual / MCP-tool-driven and is NOT covered here.
"""

from helpers import run_wire, write_descriptor, write_twb


def write_hyper(tmp_path, filename='extract.hyper'):
    path = tmp_path / filename
    path.write_bytes(b'DUMMYHYPERBINARY')  # content is never read; only its presence matters
    return str(path)


HYPER_FIELDS = [
    {"name": "city", "datatype": "string"},
    {"name": "population", "datatype": "integer"},
    {"name": "area_km2", "datatype": "real"},
]


def test_hyper_happy_path_wires_from_descriptor(tmp_path):
    twb_path = write_twb(tmp_path)
    hyper_path = write_hyper(tmp_path)
    desc_path = write_descriptor(tmp_path, {"connectionName": "federated.abc123", "fields": HYPER_FIELDS})
    result = run_wire(twb_path, hyper_path, desc_path)

    assert result.returncode == 0
    assert result.stdout.strip() == twb_path
    assert "✓ Wired embedded Hyper datasource 'Extract' (federated.abc123) with 3 field(s)" in result.stderr
    assert f'✓ Copied extract.hyper to {tmp_path / "Data" / "extract.hyper"}' in result.stderr

    copied = tmp_path / 'Data' / 'extract.hyper'
    assert copied.read_bytes() == b'DUMMYHYPERBINARY'

    wired = open(twb_path).read()
    assert '<datasources />' not in wired
    # join-key ref counts: federated.<hash> 3x, hyper.<hash> 2x
    assert wired.count("'federated.abc123'") == 3
    assert wired.count("'hyper.abc123'") == 2
    # fixed Extract relation shape — literal tokens, not derived from the filename
    assert ("<connection authentication='auth-none' author-locale='en_US' class='hyper' "
            "dbname='Data/extract.hyper' default-settings='yes' schema='Extract' tablename='Extract' />") in wired
    assert "<relation connection='hyper.abc123' name='Extract' table='[Extract].[Extract]' type='table' />" in wired
    # no inline relation <columns> block (Hyper relies on metadata-records, like Excel)
    assert '<columns>' not in wired
    # metadata-records: Hyper remote-type map (string 129, integer 20, real 5), parent-name = 'Extract'
    assert '<remote-type>129</remote-type>' in wired
    assert '<remote-type>20</remote-type>' in wired
    assert '<remote-type>5</remote-type>' in wired
    assert '<parent-name>[Extract]</parent-name>' in wired
    # view side shared with the other connectors
    assert "<column-instance column='[population]' derivation='Sum' name='[sum:population:qk]' pivot='key' type='quantitative' />" in wired


def test_hyper_descriptor_role_override_applies(tmp_path):
    twb_path = write_twb(tmp_path)
    hyper_path = write_hyper(tmp_path)
    desc_path = write_descriptor(tmp_path, {
        "connectionName": "federated.abc123",
        "fields": [
            {"name": "city", "datatype": "string"},
            {"name": "population", "datatype": "integer", "role": "dimension"},
        ],
    })
    result = run_wire(twb_path, hyper_path, desc_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    # role forced to dimension -> Count/None even though datatype is integer
    assert "<column-instance column='[population]' derivation='None' name='[none:population:nk]' pivot='key' type='quantitative' />" in wired


def test_hyper_without_descriptor_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    hyper_path = write_hyper(tmp_path)
    result = run_wire(twb_path, hyper_path)

    assert result.returncode == 1
    assert "require a descriptor.json with a non-empty 'fields' list" in result.stderr


def test_hyper_empty_fields_list_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    hyper_path = write_hyper(tmp_path)
    desc_path = write_descriptor(tmp_path, {"connectionName": "federated.abc123", "fields": []})
    result = run_wire(twb_path, hyper_path, desc_path)

    assert result.returncode == 1
    assert "require a descriptor.json with a non-empty 'fields' list" in result.stderr


def test_hyper_field_missing_datatype_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    hyper_path = write_hyper(tmp_path)
    desc_path = write_descriptor(tmp_path, {
        "connectionName": "federated.abc123",
        "fields": [
            {"name": "city", "datatype": "string"},
            {"name": "population"},  # name present but datatype omitted
        ],
    })
    result = run_wire(twb_path, hyper_path, desc_path)

    assert result.returncode == 1
    assert 'Hyper descriptor field "population" at position 1 is missing a "datatype".' in result.stderr
    # must NOT have produced a wired .twb with a stringified None local-type
    wired = open(twb_path).read()
    assert '<local-type>None</local-type>' not in wired
    assert '<datasources />' in wired  # anchors untouched — nothing was wired
