"""Hyper (.hyper) connector: `.hyper` -> `federated`/`hyper` connection,
WIRING-ONLY.

.hyper is a proprietary binary extract with no stdlib-readable schema, and
tableauhyperapi is out of scope — so this connector CANNOT introspect the file.
The caller must supply a descriptor.json with a non-empty 'fields' list; this
path only wires the (fixed) Extract relation shape a real Tableau-authored
.hyper workbook uses. name='Extract' / table='[Extract].[Extract]' are FIXED
literal tokens, not derived from the filename or relation name.
"""

from connectors.common import die, esc

# Hyper-specific remote-type codes (keyed by datatype, connector-specific).
_HYPER_REMOTE_TYPE = {'string': 129, 'integer': 20, 'real': 5}


def introspect_hyper(source_path, descriptor):
    """Produce columns from the descriptor's 'fields' list — a .hyper file's schema
    is not stdlib-readable, so there is nothing to read from source_path. Role, if
    given, is applied later by main()'s override-by-name mechanism; this only emits
    the base {name, datatype} columns. die() if no usable descriptor fields."""
    fields = descriptor.get('fields') if isinstance(descriptor, dict) else None
    if not isinstance(fields, list) or len(fields) == 0:
        die("`.hyper` files require a descriptor.json with a non-empty 'fields' list "
            "— the script cannot introspect a .hyper file's schema.")
        return
    # A .hyper's schema is descriptor-supplied, so both name and datatype must be
    # present here — there is no file to fall back on. Mirror main()'s empty-name
    # rejection but also require datatype, or esc(None) would emit <local-type>None</local-type>.
    columns = []
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            die(f'Hyper descriptor field at position {i} must be an object with a "name" and "datatype".')
        if not f.get('name'):
            die(f'Hyper descriptor field at position {i} is missing a "name".')
        if not f.get('datatype'):
            die(f'Hyper descriptor field "{f.get("name")}" at position {i} is missing a "datatype".')
        columns.append({'name': f['name'], 'datatype': f['datatype']})
    return columns, {}


def build_hyper_root(ctx):
    """Root `<datasources>` block for the Hyper connector — matches real
    Tableau-Desktop-authored .hyper workbooks: fixed Extract relation (no inline
    <columns> block, like Excel), remote-type 129/20/5, parent-name = the relation's
    own name (the literal 'Extract')."""
    fields = ctx['fields']

    metadata_records = '\n'.join(
        f"""          <metadata-record class='column'>
            <remote-name>{esc(f['name'])}</remote-name>
            <remote-type>{_HYPER_REMOTE_TYPE.get(f['datatype'], 129)}</remote-type>
            <local-name>{esc(f['localName'])}</local-name>
            <parent-name>[Extract]</parent-name>
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
            <connection authentication='auth-none' author-locale='en_US' class='hyper' dbname='Data/{esc(ctx['filename'])}' default-settings='yes' schema='Extract' tablename='Extract' />
          </named-connection>
        </named-connections>
        <relation connection='{esc(ctx['named_connection_name'])}' name='Extract' table='[Extract].[Extract]' type='table' />
        <metadata-records>
{metadata_records}
        </metadata-records>
      </connection>
      <aliases enabled='yes' />
    </datasource>
  </datasources>"""


CONNECTOR = {
    'label': 'Hyper',
    'header_label': 'Hyper descriptor',
    'named_prefix': 'hyper.',
    'introspect': introspect_hyper,
    'build_root': build_hyper_root,
}
