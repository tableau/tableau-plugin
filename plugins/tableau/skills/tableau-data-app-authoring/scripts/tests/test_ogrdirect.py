"""
Regression coverage for wire_embedded_datasource.py's shapefile/ogrdirect
connector.

Builds a minimal-but-valid shapefile .zip in-process: a hand-constructed DBF
header (the only part the script parses) plus stub .shp/.shx members, zipped
with stdlib zipfile — no pyshp/GDAL and no checked-in binary fixture needed.

NOTE: this pytest suite only proves the XML-splicing contract (what XML the
script writes into the .twb). End-to-end validation — scaffold -> wire ->
package -> publish -> query-datasource against a real Tableau site — is
manual / MCP-tool-driven and is NOT covered here.
"""

import os
import re
import struct
import zipfile

from helpers import run_wire, write_descriptor, write_twb


def _make_dbf(fields):
    # fields: list of (name, type_char, length, decimal_count). Emits a 32-byte file
    # header (contents irrelevant to the parser) + one 32-byte descriptor per field +
    # a 0x0D terminator, matching the DBF layout the script reads.
    header = b'\x03' + b'\x00' * 31
    descriptors = b''
    for name, type_char, length, decimals in fields:
        name_bytes = name.encode('ascii')[:11].ljust(11, b'\x00')
        descriptors += struct.pack(
            '<11sc4sBB14s', name_bytes, type_char.encode('ascii'), b'\x00' * 4, length, decimals, b'\x00' * 14
        )
    return header + descriptors + b'\x0d'


def write_shapefile_zip(tmp_path, dbf_fields, filename='regions.zip', include_dbf=True):
    path = tmp_path / filename
    base = os.path.splitext(filename)[0]
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(f'{base}.shp', b'\x00' * 100)  # stub geometry part, never parsed
        z.writestr(f'{base}.shx', b'\x00' * 100)  # stub index part, never parsed
        if include_dbf:
            z.writestr(f'{base}.dbf', _make_dbf(dbf_fields))
    return str(path)


# region -> string (C), population -> integer (N, 0 decimals), density -> real (N, 2 decimals)
SHAPEFILE_FIELDS = [
    ('region', 'C', 20, 0),
    ('population', 'N', 10, 0),
    ('density', 'N', 12, 2),
]


def test_zip_happy_path_reads_dbf_and_synthesizes_geometry(tmp_path):
    twb_path = write_twb(tmp_path)
    zip_path = write_shapefile_zip(tmp_path, SHAPEFILE_FIELDS)
    desc_path = write_descriptor(tmp_path, {"connectionName": "federated.abc123"})
    result = run_wire(twb_path, zip_path, desc_path)

    assert result.returncode == 0
    assert result.stdout.strip() == twb_path
    # 3 DBF fields + 1 synthetic Geometry field
    assert "✓ Wired embedded Shapefile datasource 'Regions' (federated.abc123) with 4 field(s)" in result.stderr
    assert f'✓ Copied regions.zip to {tmp_path / "Data" / "regions.zip"}' in result.stderr

    copied = tmp_path / 'Data' / 'regions.zip'
    assert copied.read_bytes() == open(zip_path, 'rb').read()

    wired = open(twb_path).read()
    assert '<datasources />' not in wired
    # join-key ref counts: federated.<hash> 3x, ogrdirect.<hash> 2x
    assert wired.count("'federated.abc123'") == 3
    assert wired.count("'ogrdirect.abc123'") == 2
    # ogrdirect connection: directory/filename are SEPARATE attrs (not concatenated like Excel)
    assert ("<connection class='ogrdirect' directory='Data' filename='regions.zip' "
            "server='' tablename='' workgroup-auth-mode='as-is' />") in wired
    # relation named after the zip's base filename, plain <columns> block (no header attr)
    assert "<relation connection='ogrdirect.abc123' name='regions' table='[regions]' type='table'>" in wired
    assert "<columns>" in wired
    assert "<column datatype='string' name='region' ordinal='0' />" in wired
    assert "<column datatype='integer' name='population' ordinal='1' />" in wired
    assert "<column datatype='real' name='density' ordinal='2' />" in wired
    # synthetic Geometry field is always appended last
    assert "<column datatype='spatial' name='Geometry' ordinal='3' />" in wired
    # remote-type map: string 129, integer 20, real 5 (inferred), spatial 128
    assert '<remote-type>129</remote-type>' in wired
    assert '<remote-type>20</remote-type>' in wired
    assert '<remote-type>5</remote-type>' in wired
    assert '<remote-type>128</remote-type>' in wired
    assert '<parent-name>[regions]</parent-name>' in wired
    # spatial field aggregates with Collect (derive_field's spatial branch), everywhere
    assert '<aggregation>Collect</aggregation>' in wired
    assert "<column aggregation='Collect' datatype='spatial' name='[Geometry]' role='dimension' type='nominal' />" in wired


def test_zip_dbf_type_byte_mapping(tmp_path):
    # F (float w/ decimals) -> real; D (date) and L (logical) punt to string in v1.
    twb_path = write_twb(tmp_path)
    zip_path = write_shapefile_zip(tmp_path, [
        ('memo_col', 'M', 40, 0),
        ('float_col', 'F', 10, 3),
        ('date_col', 'D', 8, 0),
        ('bool_col', 'L', 1, 0),
    ], filename='layers.zip')
    result = run_wire(twb_path, zip_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    assert "<column datatype='string' name='memo_col' ordinal='0' />" in wired
    assert "<column datatype='real' name='float_col' ordinal='1' />" in wired
    assert "<column datatype='string' name='date_col' ordinal='2' />" in wired
    assert "<column datatype='string' name='bool_col' ordinal='3' />" in wired


def test_zip_caption_defaults_from_filename(tmp_path):
    twb_path = write_twb(tmp_path)
    zip_path = write_shapefile_zip(tmp_path, SHAPEFILE_FIELDS, filename='world_regions.zip')
    result = run_wire(twb_path, zip_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    assert "caption='World Regions'" in wired


def test_zip_generated_connection_name_when_omitted(tmp_path):
    twb_path = write_twb(tmp_path)
    zip_path = write_shapefile_zip(tmp_path, SHAPEFILE_FIELDS)
    result = run_wire(twb_path, zip_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    assert re.search(r"federated\.[a-z0-9]+", wired)
    assert re.search(r"ogrdirect\.[a-z0-9]+", wired)


def test_zip_without_dbf_member_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    zip_path = write_shapefile_zip(tmp_path, SHAPEFILE_FIELDS, include_dbf=False)
    result = run_wire(twb_path, zip_path)

    assert result.returncode == 1
    assert 'No .dbf member found' in result.stderr
