"""Excel (.xlsx) connector: `.xlsx` -> `federated`/`excel-direct` connection
(column types sniffed from the first sheet's cell `t` attributes).

.xlsx is a zip of XML — read it with stdlib zipfile + ElementTree, no openpyxl.
"""

import os
import posixpath
import xml.etree.ElementTree as ET
import zipfile

from connectors.common import die, esc

_SS_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
_REL_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
# Excel-specific remote-type codes (differ from CSV's map — codes are connector-specific).
_XLSX_REMOTE_TYPE = {'string': 130, 'integer': 20, 'real': 5}


def _local(tag):
    # Strip the `{namespace}` prefix ElementTree prepends, so we can match by local name.
    return tag.split('}', 1)[-1]


def _col_index(ref, fallback):
    # 'B7' -> 1 (0-based column). No cell ref -> positional fallback.
    letters = ''.join(ch for ch in (ref or '') if ch.isalpha())
    if not letters:
        return fallback
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch.upper()) - ord('A') + 1)
    return idx - 1


def _cell_value(cell, shared_strings):
    # Return (t, text) for a <c> cell: t is its type attr, text its display string.
    t = cell.get('t')
    if t == 'inlineStr':
        text = ''.join(x.text or '' for x in cell.iter() if _local(x.tag) == 't')
        return t, text
    raw = None
    for child in cell:
        if _local(child.tag) == 'v':
            raw = child.text
            break
    if raw is None:
        return t, ''
    if t == 's':
        try:
            return t, shared_strings[int(raw)]
        except (ValueError, IndexError):
            return t, ''
    return t, raw


def infer_datatype_xlsx(cells):
    # cells: list of (t, text). Sniff by cell type: numeric (t absent or 'n') ->
    # integer/real by decimal-point heuristic (same style as CSV's infer_datatype);
    # shared string 's', boolean 'b', 'str'/'inlineStr' -> string.
    non_empty = [(t, v) for (t, v) in cells if v not in ('', None)]
    if not non_empty:
        return 'string'
    if all(t in (None, 'n') for (t, v) in non_empty):
        # v1 cut: no numFmt/styles.xml cross-reference, so date-looking numbers stay numeric.
        return 'real' if any('.' in v for (t, v) in non_empty) else 'integer'
    return 'string'


def introspect_xlsx(source_path, descriptor):
    """Read the first sheet (or descriptor['sheet']) of an .xlsx via stdlib zip/XML:
    return (columns, meta) where meta['sheet_name'] is the literal sheet name."""
    try:
        zf = zipfile.ZipFile(source_path)
    except Exception as error:
        die(f'Could not open .xlsx (not a valid zip?) at {source_path}: {error}')
        return
    with zf:
        names = zf.namelist()

        try:
            wb = ET.fromstring(zf.read('xl/workbook.xml'))
            rels = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
        except (KeyError, ET.ParseError) as error:
            die(f'Malformed .xlsx (missing/invalid workbook parts) at {source_path}: {error}')
            return

        rid_to_target = {
            el.get('Id'): el.get('Target')
            for el in rels.iter() if _local(el.tag) == 'Relationship'
        }
        sheets = [
            (el.get('name'), el.get(f'{{{_REL_NS}}}id'))
            for el in wb.iter() if _local(el.tag) == 'sheet'
        ]
        if not sheets:
            die(f'No sheets found in {os.path.basename(source_path)}.')

        wanted = descriptor.get('sheet') if isinstance(descriptor, dict) else None
        if wanted:
            match = next((s for s in sheets if s[0] == wanted), None)
            if match is None:
                available = ', '.join(s[0] for s in sheets)
                die(f'Sheet "{wanted}" not found in {os.path.basename(source_path)} (available: {available}).')
            sheet_name, rid = match
        else:
            sheet_name, rid = sheets[0]

        target = rid_to_target.get(rid)
        if not target:
            die(f'Could not resolve sheet "{sheet_name}" to a worksheet part in {os.path.basename(source_path)}.')
        sheet_path = target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join('xl', target))

        shared_strings = []
        if 'xl/sharedStrings.xml' in names:
            sst = ET.fromstring(zf.read('xl/sharedStrings.xml'))
            for si in sst:
                if _local(si.tag) == 'si':
                    shared_strings.append(''.join(t.text or '' for t in si.iter() if _local(t.tag) == 't'))

        try:
            sheet = ET.fromstring(zf.read(sheet_path))
        except (KeyError, ET.ParseError) as error:
            die(f'Could not read worksheet {sheet_path} in {os.path.basename(source_path)}: {error}')
            return

    rows = [el for el in sheet.iter() if _local(el.tag) == 'row']
    if len(rows) < 2:
        die(f'Excel sheet "{sheet_name}" must have a header row plus at least one data row.')

    def cells_of(row):
        return [c for c in row if _local(c.tag) == 'c']

    header_by_idx = {}
    for pos, c in enumerate(cells_of(rows[0])):
        idx = _col_index(c.get('r'), pos)
        header_by_idx[idx] = _cell_value(c, shared_strings)[1]
    col_indices = sorted(header_by_idx)

    per_col = {i: [] for i in col_indices}
    for row in rows[1:201]:  # sample up to 200 rows for type inference (matches CSV depth)
        row_by_idx = {}
        for pos, c in enumerate(cells_of(row)):
            idx = _col_index(c.get('r'), pos)
            row_by_idx[idx] = _cell_value(c, shared_strings)
        for i in col_indices:
            per_col[i].append(row_by_idx.get(i, (None, '')))

    columns = [
        {'name': header_by_idx[i], 'datatype': infer_datatype_xlsx(per_col[i])}
        for i in col_indices
    ]
    return columns, {'sheet_name': sheet_name}


def build_xlsx_root(ctx):
    """Root `<datasources>` block for the Excel/excel-direct connector — matches
    real Tableau-Desktop-authored .xlsx workbooks: no root <column> overrides
    (metadata-records alone), remote-type 130/20/5, parent-name = the sheet name."""
    fields = ctx['fields']
    sheet_name = ctx['meta']['sheet_name']

    relation_columns = '\n'.join(
        f"        <column datatype='{esc(f['datatype'])}' name='{esc(f['name'])}' ordinal='{f['ordinal']}' />"
        for f in fields
    )

    metadata_records = '\n'.join(
        f"""          <metadata-record class='column'>
            <remote-name>{esc(f['name'])}</remote-name>
            <remote-type>{_XLSX_REMOTE_TYPE.get(f['datatype'], 130)}</remote-type>
            <local-name>{esc(f['localName'])}</local-name>
            <parent-name>[{esc(sheet_name)}]</parent-name>
            <remote-alias>{esc(f['name'])}</remote-alias>
            <ordinal>{f['ordinal']}</ordinal>
            <local-type>{esc(f['datatype'])}</local-type>
            <aggregation>{f['aggregation']}</aggregation>
            <contains-null>true</contains-null>
          </metadata-record>"""
        for f in fields
    )

    return f"""<datasources>
    <datasource caption='{esc(ctx['caption'])}' inline='true' name='{esc(ctx['connection_name'])}' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='{esc(ctx['filename'])}' name='{esc(ctx['named_connection_name'])}'>
            <connection class='excel-direct' cleaning='no' compat='no' dataRefreshTime='' filename='Data/{esc(ctx['filename'])}' interpretationMode='0' server='' validate='no' />
          </named-connection>
        </named-connections>
        <relation connection='{esc(ctx['named_connection_name'])}' name='{esc(sheet_name)}' table='[{esc(sheet_name)}$]' type='table'>
          <columns header='yes'>
{relation_columns}
          </columns>
        </relation>
        <metadata-records>
{metadata_records}
        </metadata-records>
      </connection>
      <aliases enabled='yes' />
    </datasource>
  </datasources>"""


CONNECTOR = {
    'label': 'Excel',
    'header_label': 'Excel sheet header',
    'named_prefix': 'excel-direct.',
    'introspect': introspect_xlsx,
    'build_root': build_xlsx_root,
}
