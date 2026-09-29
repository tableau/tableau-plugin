"""CSV connector: `.csv` -> `federated`/`textscan` connection (column types
regex-sniffed from sampled raw CSV rows)."""

import re

from connectors.common import die, esc


# Minimal CSV line splitter: no embedded-comma/quote support. Good enough for the
# flat, simple CSVs this path is meant for; a quoted-field CSV needs a real parser.
def split_csv_line(line):
    return [cell.strip() for cell in line.split(',')]


def infer_datatype(values):
    non_empty = [v for v in values if v != '']
    if len(non_empty) == 0:
        return 'string'
    if all(re.fullmatch(r'-?\d+', v) for v in non_empty):
        return 'integer'
    if all(re.fullmatch(r'-?\d+(\.\d+)?', v) for v in non_empty):
        return 'real'
    return 'string'


def introspect_csv(source_path, descriptor):
    """Read a CSV: return (columns, meta). columns is [{'name', 'datatype'}...]
    with datatype REGEX-sniffed from sampled rows; meta carries no extra bits."""
    try:
        with open(source_path, 'r', encoding='utf-8') as f:
            raw = f.read()
    except Exception as error:
        die(f'Could not read CSV at {source_path}: {error}')
        return
    csv_lines = [line for line in re.split(r'\r\n|\r|\n', raw) if len(line) > 0]
    if len(csv_lines) < 2:
        die('CSV must have a header row plus at least one data row.')

    header = split_csv_line(csv_lines[0])
    sample_rows = [split_csv_line(line) for line in csv_lines[1:201]]  # sample up to 200 rows for type inference

    columns = []
    for i, name in enumerate(header):
        column_values = [(row[i] if i < len(row) else '') for row in sample_rows]
        columns.append({'name': name, 'datatype': infer_datatype(column_values)})
    return columns, {}


def build_csv_root(ctx):
    """Root `<datasources>` block for the CSV/textscan connector — byte-for-byte
    the shape validated end-to-end (federated wrapper, named textscan connection,
    root <column> overrides, remote-type 5/129, parent-name = [<filename>])."""
    fields = ctx['fields']
    metadata_records = '\n'.join(
        f"""          <metadata-record class='column'>
            <remote-name>{esc(f['name'])}</remote-name>
            <remote-type>{5 if f['type'] == 'quantitative' else 129}</remote-type>
            <local-name>{esc(f['localName'])}</local-name>
            <parent-name>[{esc(ctx['filename'])}]</parent-name>
            <remote-alias>{esc(f['name'])}</remote-alias>
            <ordinal>{f['ordinal']}</ordinal>
            <local-type>{esc(f['datatype'])}</local-type>
            <aggregation>{f['aggregation']}</aggregation>
            <contains-null>true</contains-null>
          </metadata-record>"""
        for f in fields
    )

    root_columns = '\n'.join(
        f"      <column datatype='{esc(f['datatype'])}' name='{esc(f['localName'])}' role='{f['role']}' type='{f['type']}' />"
        for f in fields
    )

    return f"""<datasources>
    <datasource caption='{esc(ctx['caption'])}' inline='true' name='{esc(ctx['connection_name'])}' version='18.1'>
      <connection class='federated'>
        <named-connections>
          <named-connection caption='{esc(ctx['filename'])}' name='{esc(ctx['named_connection_name'])}'>
            <connection class='textscan' directory='Data' filename='{esc(ctx['filename'])}' password='' server='' />
          </named-connection>
        </named-connections>
        <relation connection='{esc(ctx['named_connection_name'])}' name='{esc(ctx['filename'])}' table='[{esc(ctx['table_base_name'])}#csv]' type='table' />
        <metadata-records>
{metadata_records}
        </metadata-records>
      </connection>
      <aliases enabled='yes' />
{root_columns}
    </datasource>
  </datasources>"""


CONNECTOR = {
    'label': 'CSV',
    'header_label': 'CSV header',
    'named_prefix': 'textscan.',
    'introspect': introspect_csv,
    'build_root': build_csv_root,
}
