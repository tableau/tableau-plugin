"""
Regression coverage for wire_embedded_datasource.py's JSON
(semistructpassivestore-direct) connector.

Writes a minimal flat JSON array fixture directly (stdlib json.dumps — no
external sample needed) and drives the wiring script against it.

NOTE: this pytest suite only proves the XML-splicing contract (what XML the
script writes into the .twb). End-to-end validation — scaffold -> wire ->
package -> publish -> query-datasource against a real Tableau site — is
manual / MCP-tool-driven and is NOT covered here.
"""

import json

from helpers import run_wire, write_descriptor, write_twb


def write_json(tmp_path, rows, filename='products.json'):
    path = tmp_path / filename
    path.write_text(json.dumps(rows))
    return str(path)


PRODUCT_ROWS = [
    {"id": 1, "product": "Widget", "category": "Tools", "price": 9.99, "in_stock": True, "rating": 4.5},
    {"id": 2, "product": "Gadget", "category": "Electronics", "price": 19.5, "in_stock": False, "rating": 3.8},
]


def test_json_happy_path_wires_from_real_file(tmp_path):
    twb_path = write_twb(tmp_path)
    json_path = write_json(tmp_path, PRODUCT_ROWS)
    desc_path = write_descriptor(tmp_path, {"connectionName": "federated.abc123"})
    result = run_wire(twb_path, json_path, desc_path)

    assert result.returncode == 0
    assert result.stdout.strip() == twb_path
    assert "✓ Wired embedded JSON datasource 'Products' (federated.abc123) with 6 field(s)" in result.stderr
    assert f'✓ Copied products.json to {tmp_path / "Data" / "products.json"}' in result.stderr

    copied = tmp_path / 'Data' / 'products.json'
    assert copied.read_bytes() == open(json_path, 'rb').read()

    wired = open(twb_path).read()
    assert '<datasources />' not in wired
    # join-key ref counts: federated.<hash> 3x, semistructpassivestore-direct.<hash> 2x
    assert wired.count("'federated.abc123'") == 3
    assert wired.count("'semistructpassivestore-direct.abc123'") == 2
    # directory/filename are SEPARATE attrs, using OUR OWN Data/ convention (not the
    # ground-truth workbook's incidental 'Data/Downloads')
    assert ("<connection class='semistructpassivestore-direct' directory='Data' "
            "filename='products.json' password='' server=''>") in wired
    assert "<semistruct-schema table='[products.json]'>" in wired
    assert "<map key='{root}' value='true' />" in wired
    # self-closing relation, full filename (with extension) as name/table — no inline <columns>
    assert ("<relation connection='semistructpassivestore-direct.abc123' name='products.json' "
            "table='[products.json]' type='table' />") in wired
    assert '<columns>' not in wired
    assert '<parent-name>[products.json]</parent-name>' in wired
    # remote-type map: string 130 (NOT 129 — different from CSV/Excel/Hyper/ogrdirect), real 5, boolean 11
    assert '<remote-type>130</remote-type>' in wired
    assert '<remote-type>5</remote-type>' in wired
    assert '<remote-type>11</remote-type>' in wired
    assert '<remote-type>20</remote-type>' not in wired  # no integer-typed field in this fixture
    # boolean flows through the shared derive_field logic with no special-casing
    assert '<local-type>boolean</local-type>' in wired
    assert "<column-instance column='[in_stock]' derivation='None' name='[none:in_stock:nk]' pivot='key' type='nominal' />" in wired
    # no CSV-style bare root <column> override for plain fields (Excel/Hyper/ogrdirect convention)
    assert "<column datatype='real' name='[price]' role='measure' type='quantitative' />" not in wired


def test_json_numbers_always_typed_real_not_integer(tmp_path):
    # id's values (1, 2) look like plain integers, but JSON has no distinct int type —
    # Tableau Desktop's own introspection always uses real/remote-type 5 for JSON numbers.
    twb_path = write_twb(tmp_path)
    json_path = write_json(tmp_path, PRODUCT_ROWS)
    result = run_wire(twb_path, json_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    assert "<remote-name>id</remote-name>" in wired
    id_record = wired[wired.index('<remote-name>id</remote-name>'):]
    assert '<local-type>real</local-type>' in id_record[:400]
    assert '<local-type>integer</local-type>' not in id_record[:400]


def test_json_nested_value_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    json_path = write_json(tmp_path, [{"id": 1, "tags": ["a", "b"]}])
    result = run_wire(twb_path, json_path)

    assert result.returncode == 1
    assert 'nested object/array' in result.stderr


def test_json_non_array_top_level_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    json_path = tmp_path / 'products.json'
    json_path.write_text(json.dumps({"id": 1}))
    result = run_wire(twb_path, str(json_path))

    assert result.returncode == 1
    assert 'must be a non-empty array of objects' in result.stderr


def test_json_empty_array_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    json_path = write_json(tmp_path, [])
    result = run_wire(twb_path, json_path)

    assert result.returncode == 1
    assert 'must be a non-empty array of objects' in result.stderr


def test_json_descriptor_role_override_applies(tmp_path):
    twb_path = write_twb(tmp_path)
    json_path = write_json(tmp_path, PRODUCT_ROWS)
    desc_path = write_descriptor(tmp_path, {
        "connectionName": "federated.abc123",
        "fields": [{"name": "rating", "role": "dimension"}],
    })
    result = run_wire(twb_path, json_path, desc_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    # role forced to dimension -> Count/None even though datatype is real
    assert "<column-instance column='[rating]' derivation='None' name='[none:rating:nk]' pivot='key' type='quantitative' />" in wired
