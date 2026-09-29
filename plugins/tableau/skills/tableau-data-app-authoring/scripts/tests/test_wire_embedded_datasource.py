"""
Regression coverage for wire_embedded_datasource.py, the Python port of
wire-embedded-datasource.mjs, now covering both the CSV/textscan and the
Excel/excel-direct embedded connectors.

Every CSV scenario here was verified byte-for-byte (stdout, stderr, exit code,
the resulting wired .twb XML, and the copied file) against the original Node
script before the .mjs was removed. These tests exercise the CLI contract
directly (subprocess), matching how SKILL.md invokes the script.

NOTE: this pytest suite only proves the XML-splicing contract (what XML the
script writes into the .twb). End-to-end validation — scaffold -> wire ->
package -> publish -> query-datasource against a real Tableau site — is
manual / MCP-tool-driven and is NOT covered here.
"""

import json
import os
import re
import struct
import subprocess
import sys
import zipfile

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


def _col_letter(i):
    s = ''
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        s = chr(65 + rem) + s
    return s


def _xesc(value):
    return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# rows: list of lists; row 0 is the header. int/float cells become numeric cells,
# everything else a shared string. Builds a minimal-but-valid .xlsx (enough for the
# script's stdlib zip/XML reader; it need not open in real Excel).
def write_xlsx(tmp_path, rows, filename='players.xlsx', sheet_name='Sheet1'):
    shared = []
    shared_index = {}

    def intern(text):
        if text not in shared_index:
            shared_index[text] = len(shared)
            shared.append(text)
        return shared_index[text]

    row_xml = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, val in enumerate(row):
            ref = f'{_col_letter(c)}{r}'
            if isinstance(val, bool):
                cells.append(f"<c r='{ref}' t='b'><v>{1 if val else 0}</v></c>")
            elif isinstance(val, (int, float)):
                cells.append(f"<c r='{ref}'><v>{val}</v></c>")
            else:
                cells.append(f"<c r='{ref}' t='s'><v>{intern(str(val))}</v></c>")
        row_xml.append(f"<row r='{r}'>{''.join(cells)}</row>")

    sheet_xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>"
        f"<sheetData>{''.join(row_xml)}</sheetData></worksheet>"
    )
    sst_xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<sst xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' "
        f"count='{len(shared)}' uniqueCount='{len(shared)}'>"
        + ''.join(f'<si><t>{_xesc(s)}</t></si>' for s in shared)
        + '</sst>'
    )
    workbook_xml = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<workbook xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' "
        "xmlns:r='http://schemas.openxmlformats.org/officeDocument/2006/relationships'>"
        f"<sheets><sheet name='{_xesc(sheet_name)}' sheetId='1' r:id='rId1'/></sheets></workbook>"
    )
    workbook_rels = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
        "<Relationship Id='rId1' "
        "Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet' "
        "Target='worksheets/sheet1.xml'/>"
        "<Relationship Id='rId2' "
        "Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings' "
        "Target='sharedStrings.xml'/>"
        "</Relationships>"
    )
    root_rels = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<Relationships xmlns='http://schemas.openxmlformats.org/package/2006/relationships'>"
        "<Relationship Id='rId1' "
        "Type='http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument' "
        "Target='xl/workbook.xml'/></Relationships>"
    )
    content_types = (
        "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>"
        "<Types xmlns='http://schemas.openxmlformats.org/package/2006/content-types'>"
        "<Default Extension='rels' ContentType='application/vnd.openxmlformats-package.relationships+xml'/>"
        "<Default Extension='xml' ContentType='application/xml'/>"
        "<Override PartName='/xl/workbook.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'/>"
        "<Override PartName='/xl/worksheets/sheet1.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml'/>"
        "<Override PartName='/xl/sharedStrings.xml' ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml'/>"
        "</Types>"
    )

    path = tmp_path / filename
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', root_rels)
        z.writestr('xl/workbook.xml', workbook_xml)
        z.writestr('xl/_rels/workbook.xml.rels', workbook_rels)
        z.writestr('xl/worksheets/sheet1.xml', sheet_xml)
        z.writestr('xl/sharedStrings.xml', sst_xml)
    return str(path)


XLSX_HAPPY_ROWS = [
    ['full_name', 'country', 'titles', 'turned_pro'],
    ['Roger', 'Switzerland', 20, 1998],
    ['Rafael', 'Spain', 22, 2001],
]


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


def test_unsupported_extension_lists_supported_types(tmp_path):
    twb_path = write_twb(tmp_path)
    src_path = write_csv(tmp_path, "a,b\n1,2\n", filename='players.txt')
    result = run_wire(twb_path, src_path)

    assert result.returncode == 1
    assert 'Unsupported file type' in result.stderr
    # message must enumerate every supported extension
    assert '.csv' in result.stderr
    assert '.xlsx' in result.stderr
    assert '.hyper' in result.stderr
    assert '.zip' in result.stderr


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


# --- Excel (.xlsx) connector -------------------------------------------------


def test_xlsx_happy_path_infers_types_and_copies_file(tmp_path):
    twb_path = write_twb(tmp_path)
    xlsx_path = write_xlsx(tmp_path, XLSX_HAPPY_ROWS)
    desc_path = write_descriptor(tmp_path, {"connectionName": "federated.abc123"})
    result = run_wire(twb_path, xlsx_path, desc_path)

    assert result.returncode == 0
    assert result.stdout.strip() == twb_path
    assert "✓ Wired embedded Excel datasource 'Players' (federated.abc123) with 4 field(s)" in result.stderr
    assert f'✓ Copied players.xlsx to {tmp_path / "Data" / "players.xlsx"}' in result.stderr

    # source .xlsx copied verbatim into Data/
    copied = tmp_path / 'Data' / 'players.xlsx'
    assert copied.read_bytes() == open(xlsx_path, 'rb').read()

    wired = open(twb_path).read()
    assert '<datasources />' not in wired
    # join-key ref counts: federated.<hash> 3x, excel-direct.<hash> 2x
    assert wired.count("'federated.abc123'") == 3
    assert wired.count("'excel-direct.abc123'") == 2
    # excel-direct connection + relation shape (literal sheet name + [Sheet1$] table)
    assert "<connection class='excel-direct' cleaning='no' compat='no' dataRefreshTime='' filename='Data/players.xlsx' interpretationMode='0' server='' validate='no' />" in wired
    assert "<relation connection='excel-direct.abc123' name='Sheet1' table='[Sheet1$]' type='table'>" in wired
    assert "<columns header='yes'>" in wired
    assert "<column datatype='integer' name='titles' ordinal='2' />" in wired
    # metadata-records: Excel remote-type map (integer 20, string 130), parent-name = sheet name
    assert '<remote-type>20</remote-type>' in wired
    assert '<remote-type>130</remote-type>' in wired
    assert '<parent-name>[Sheet1]</parent-name>' in wired
    # NO root-level <column> overrides for plain fields (excel relies on metadata-records)
    assert "<column datatype='integer' name='[titles]' role='measure' type='quantitative' />" not in wired
    # view side is shared with CSV
    assert "<column-instance column='[titles]' derivation='Sum' name='[sum:titles:qk]' pivot='key' type='quantitative' />" in wired


def test_xlsx_descriptor_overrides_inferred_datatype_and_role(tmp_path):
    twb_path = write_twb(tmp_path)
    xlsx_path = write_xlsx(tmp_path, XLSX_HAPPY_ROWS)
    desc_path = write_descriptor(tmp_path, {
        "connectionName": "federated.abc123",
        "fields": [{"name": "turned_pro", "datatype": "real", "role": "dimension"}],
    })
    result = run_wire(twb_path, xlsx_path, desc_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    # datatype forced to real (remote-type 5) and role forced to dimension (Count/None)
    assert "<column datatype='real' name='turned_pro' ordinal='3' />" in wired
    assert "<column-instance column='[turned_pro]' derivation='None' name='[none:turned_pro:nk]' pivot='key' type='quantitative' />" in wired


def test_xlsx_caption_defaults_from_filename(tmp_path):
    twb_path = write_twb(tmp_path)
    xlsx_path = write_xlsx(tmp_path, XLSX_HAPPY_ROWS, filename='top_tennis-players.xlsx')
    result = run_wire(twb_path, xlsx_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    assert "caption='Top Tennis Players'" in wired


def test_xlsx_header_only_sheet_is_rejected(tmp_path):
    twb_path = write_twb(tmp_path)
    xlsx_path = write_xlsx(tmp_path, [['full_name', 'country']])
    result = run_wire(twb_path, xlsx_path)

    assert result.returncode == 1
    assert 'must have a header row plus at least one data row' in result.stderr


def test_xlsx_generated_connection_name_when_omitted(tmp_path):
    twb_path = write_twb(tmp_path)
    xlsx_path = write_xlsx(tmp_path, XLSX_HAPPY_ROWS)
    result = run_wire(twb_path, xlsx_path)

    assert result.returncode == 0
    wired = open(twb_path).read()
    assert re.search(r"federated\.[a-z0-9]+", wired)
    assert re.search(r"excel-direct\.[a-z0-9]+", wired)


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


# --- Hyper (.hyper) connector ------------------------------------------------
#
# .hyper is wiring-only: the script cannot introspect a proprietary binary extract,
# so the caller must supply a descriptor.json with a non-empty 'fields' list. These
# tests write a dummy .hyper (never read) and drive the descriptor-only path.


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


# --- Shapefile (.zip) connector — ogrdirect ----------------------------------
#
# Build a minimal-but-valid shapefile .zip in-process: a hand-constructed DBF header
# (the only part the script parses) plus stub .shp/.shx members, zipped with stdlib
# zipfile — no pyshp/GDAL and no checked-in binary fixture needed.


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
