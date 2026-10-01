"""
Regression coverage for wire_embedded_datasource.py's Excel/excel-direct
connector. These tests exercise the CLI contract directly (subprocess),
matching how SKILL.md invokes the script.

NOTE: this pytest suite only proves the XML-splicing contract (what XML the
script writes into the .twb). End-to-end validation — scaffold -> wire ->
package -> publish -> query-datasource against a real Tableau site — is
manual / MCP-tool-driven and is NOT covered here.
"""

import re
import zipfile

from helpers import run_wire, write_descriptor, write_twb


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
