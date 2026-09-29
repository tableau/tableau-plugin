"""JSON (.json) connector: `.json` -> `federated`/`semistructpassivestore-direct`
connection (Tableau's semi-structured/JSON connector).

Named `jsonfile.py` (not `json.py`) deliberately: wire_embedded_datasource.py
already does a top-level `import json` (stdlib, used for descriptor loading) —
`from connectors import ..., json, ...` would shadow that name.

Ground-truthed against a real Tableau-Desktop-authored workbook connecting a
flat JSON array of flat objects. v1 scope: FLAT array of FLAT objects only — a
field whose value is itself an object/array is rejected rather than silently
mistyped; nested JSON is unverified territory.

Two connector-specific quirks confirmed from that ground truth (not shared with
any other connector):
  - every JSON number is typed `real` (remote-type 5), never `integer` — JSON
    itself has no distinct int type, and Tableau Desktop's own introspection of
    a JSON number always uses `real` regardless of whether the sampled values
    look like whole numbers.
  - `boolean` is a genuinely new local-type (remote-type 11) unused by CSV/
    Excel/Hyper/ogrdirect — no special-casing needed in connectors/common.py:
    type_of() already falls through to 'nominal' and role-inference already
    defaults to 'dimension' for anything that isn't integer/real, which is
    exactly what real Tableau Desktop emits for a boolean JSON field too.

Deliberately NOT replicated from the ground-truth workbook (v1 scope, by
explicit choice, not by omission-through-guessing): Tableau Desktop also
auto-generates a synthetic 'Document Index (generated)' bookkeeping field, an
<object-graph>/internal-object-id "table" column, and per-field root-level
<column> overrides with caption/desc. Whether any of that is required for a
live query to resolve (vs. pure Desktop-authoring decoration) is UNCONFIRMED.
This connector wires only the file's own real fields via metadata-records —
matching Excel/Hyper/ogrdirect's "no root <column> overrides" convention, not
CSV's — and skips the rest, same "implement the minimal proven-necessary
shape, validate live before calling it required" posture as Hyper/ogrdirect's
still-open live-query gap.
"""

import json as json_module

from connectors.common import die, esc

# Confirmed from ground truth: string=130 (note: NOT 129 — Excel/Hyper/ogrdirect's
# string code; JSON's is genuinely different), real=5, boolean=11. 'integer' is
# never produced by introspect_json itself (see module docstring) but is mapped
# here anyway so a descriptor override forcing datatype='integer' still gets a
# sane remote-type instead of silently falling back to string's code.
_JSON_REMOTE_TYPE = {'string': 130, 'real': 5, 'boolean': 11, 'integer': 20}


def _json_value_type(value):
    if isinstance(value, bool):  # must precede the int check: bool is a subclass of int
        return 'boolean'
    if isinstance(value, (int, float)):
        return 'real'
    return 'string'


def introspect_json(source_path, descriptor):
    """Read a flat JSON array of flat objects: return (columns, meta). columns is
    [{'name', 'datatype'}...], in first-seen key order, datatype inferred from
    each field's first non-null value across the array (string/real/boolean —
    numbers always map to real, never integer). die() if the top level isn't a
    non-empty array of objects, or if any field's value is itself an
    object/array (nested JSON is out of v1 scope)."""
    try:
        with open(source_path, 'r', encoding='utf-8') as f:
            data = json_module.load(f)
    except Exception as error:
        die(f'Could not read/parse JSON at {source_path}: {error}')
        return

    if not isinstance(data, list) or len(data) == 0:
        die('JSON must be a non-empty array of objects (v1 scope: flat arrays of flat objects only).')
        return
    if not all(isinstance(row, dict) for row in data):
        die('JSON array must contain only objects (v1 scope: flat arrays of flat objects only).')
        return

    order = []
    datatypes = {}
    for row in data:
        for key, value in row.items():
            if key not in datatypes:
                order.append(key)
                datatypes[key] = None
            if isinstance(value, (dict, list)):
                die(f'Field "{key}" contains a nested object/array — v1 scope supports flat JSON only.')
                return
            if value is not None and datatypes[key] is None:
                datatypes[key] = _json_value_type(value)

    columns = [{'name': key, 'datatype': datatypes[key] or 'string'} for key in order]
    return columns, {}


def build_json_root(ctx):
    """Root `<datasources>` block for the JSON/semistructpassivestore-direct
    connector — a self-closing <relation> with no inline <columns> (like Hyper,
    relies on metadata-records only) plus a <semistruct-schemas> block mapping
    the whole document root, both ground-truthed from a real Desktop-authored
    workbook. Relation/parent-name use the FULL filename (with .json extension),
    not the base name — unlike CSV/ogrdirect, which strip the extension.
    directory='Data' is our own copy convention (like ogrdirect), not the
    ground truth's incidental 'Data/Downloads' (an artifact of where that one
    sample happened to sit on disk, not a structural requirement)."""
    fields = ctx['fields']
    filename = ctx['filename']

    metadata_records = '\n'.join(
        f"""          <metadata-record class='column'>
            <remote-name>{esc(f['name'])}</remote-name>
            <remote-type>{_JSON_REMOTE_TYPE.get(f['datatype'], 130)}</remote-type>
            <local-name>{esc(f['localName'])}</local-name>
            <parent-name>[{esc(filename)}]</parent-name>
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
          <named-connection caption='{esc(filename)}' name='{esc(ctx['named_connection_name'])}'>
            <connection class='semistructpassivestore-direct' directory='Data' filename='{esc(filename)}' password='' server=''>
              <semistruct-schemas>
                <semistruct-schema table='[{esc(filename)}]'>
                  <map key='{{root}}' value='true' />
                </semistruct-schema>
              </semistruct-schemas>
            </connection>
          </named-connection>
        </named-connections>
        <relation connection='{esc(ctx['named_connection_name'])}' name='{esc(filename)}' table='[{esc(filename)}]' type='table' />
        <metadata-records>
{metadata_records}
        </metadata-records>
      </connection>
      <aliases enabled='yes' />
    </datasource>
  </datasources>"""


CONNECTOR = {
    'label': 'JSON',
    'header_label': 'JSON field list',
    'named_prefix': 'semistructpassivestore-direct.',
    'introspect': introspect_json,
    'build_root': build_json_root,
}
