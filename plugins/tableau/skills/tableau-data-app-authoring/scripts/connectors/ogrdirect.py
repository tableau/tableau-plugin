"""Shapefile (.zip) connector — ogrdirect: `.zip` -> `federated`/`ogrdirect`
connection (spatial/shapefile).

A .zip of shapefile parts (.shp/.shx/.dbf/...). No pyshp/GDAL dependency: the
field list is read straight out of the .dbf member with a minimal stdlib struct
parser, and a synthetic 'Geometry' (spatial) field is always appended.

v1 scoping call: any .zip passed to this script is ASSUMED to be a shapefile zip
— there is no content sniffing beyond finding a .dbf member. Widening this to
other zip-backed formats would need its own detection + connector entry.
"""

import os
import struct
import zipfile

from connectors.common import die, esc

# ogrdirect-specific remote-type codes. string/integer/spatial are confirmed from a
# real sample; real=5 is INFERRED by pattern-consistency with Hyper's map (no
# real-typed field existed in the sampled shapefile), not directly observed.
_OGR_REMOTE_TYPE = {'string': 129, 'integer': 20, 'spatial': 128, 'real': 5}


def _dbf_type_to_datatype(type_char, decimal_count):
    # DBF field-type byte -> our datatype. D (date) and L (logical) are punted to
    # string in v1 (a deliberate cut, not real date/boolean support).
    if type_char in ('C', 'M'):
        return 'string'
    if type_char in ('N', 'F'):
        return 'real' if decimal_count > 0 else 'integer'
    return 'string'


def _read_dbf_fields(dbf_bytes):
    """Parse a DBF header into [{'name', 'datatype'}...]. Layout: a 32-byte file
    header, then 32-byte field-descriptor records terminated by a 0x0D byte. Each
    descriptor: 11-byte null-padded ASCII name, 1-byte type char, 4 reserved bytes,
    1-byte field length, 1-byte decimal count, then reserved padding to 32 bytes."""
    fields = []
    offset = 32
    while offset < len(dbf_bytes) and dbf_bytes[offset] != 0x0D:
        descriptor = dbf_bytes[offset:offset + 32]
        if len(descriptor) < 32:
            break
        name_raw, type_char, _reserved, _length, decimal_count = struct.unpack('<11sc4sBB', descriptor[:18])
        name = name_raw.split(b'\x00', 1)[0].decode('ascii', 'replace')
        datatype = _dbf_type_to_datatype(type_char.decode('ascii', 'replace'), decimal_count)
        fields.append({'name': name, 'datatype': datatype})
        offset += 32
    return fields


def introspect_zip(source_path, descriptor):
    """Read the .dbf member's field list out of a shapefile .zip via stdlib zipfile
    + struct, then ALWAYS append a synthetic spatial 'Geometry' field (never read
    from the file). die() if the zip has no .dbf member."""
    try:
        zf = zipfile.ZipFile(source_path)
    except Exception as error:
        die(f'Could not open .zip (not a valid zip?) at {source_path}: {error}')
        return
    with zf:
        dbf_members = [n for n in zf.namelist() if n.lower().endswith('.dbf')]
        if not dbf_members:
            die(f'No .dbf member found in {os.path.basename(source_path)} — expected a shapefile .zip containing a .dbf.')
            return
        dbf_bytes = zf.read(dbf_members[0])
    columns = _read_dbf_fields(dbf_bytes)
    columns.append({'name': 'Geometry', 'datatype': 'spatial'})
    return columns, {}


def build_ogrdirect_root(ctx):
    """Root `<datasources>` block for the shapefile/ogrdirect connector — matches
    real shapefile-backed Tableau workbooks: `directory`/`filename` are SEPARATE
    attributes (unlike Excel's concatenated path), a plain <columns> block (no
    Excel header/gridOrigin/outcome attrs), remote-type 129/20/128/5, parent-name =
    the relation's own name (the layer/base filename)."""
    fields = ctx['fields']
    layer_name = ctx['table_base_name']

    relation_columns = '\n'.join(
        f"        <column datatype='{esc(f['datatype'])}' name='{esc(f['name'])}' ordinal='{f['ordinal']}' />"
        for f in fields
    )

    metadata_records = '\n'.join(
        f"""          <metadata-record class='column'>
            <remote-name>{esc(f['name'])}</remote-name>
            <remote-type>{_OGR_REMOTE_TYPE.get(f['datatype'], 129)}</remote-type>
            <local-name>{esc(f['localName'])}</local-name>
            <parent-name>[{esc(layer_name)}]</parent-name>
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
            <connection class='ogrdirect' directory='Data' filename='{esc(ctx['filename'])}' server='' tablename='' workgroup-auth-mode='as-is' />
          </named-connection>
        </named-connections>
        <relation connection='{esc(ctx['named_connection_name'])}' name='{esc(layer_name)}' table='[{esc(layer_name)}]' type='table'>
          <columns>
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
    'label': 'Shapefile',
    'header_label': 'Shapefile .dbf field list',
    'named_prefix': 'ogrdirect.',
    'introspect': introspect_zip,
    'build_root': build_ogrdirect_root,
}
