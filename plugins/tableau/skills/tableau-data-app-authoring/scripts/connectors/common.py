"""Shared helpers used by every embedded-datasource connector and the CLI:
die() (error-and-exit), esc() (XML attr/text escaping), and derive_field()
(a field's derived attributes, computed once and reused across all XML blocks).
Depends on nothing in wire_embedded_datasource.py — connectors import from here,
never the other way around, so there is no import cycle."""

import sys


def die(message):
    print(f'✗ {message}', file=sys.stderr)
    sys.exit(1)


# XML attribute-value escaping (single-quoted attrs + element text).
def esc(value):
    return (
        str(value)
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace("'", '&apos;')
        .replace('"', '&quot;')
    )


# datatype -> Tableau column `type`. Mirrors wire_datasource.py's type_of() exactly —
# the two must stay in lockstep or a descriptor override supplying datatype: "date"/
# "datetime" on the embedded path (no connector infers dates itself, but overrides
# aren't restricted to inferred values) would silently type as nominal instead of
# ordinal, diverging from the published path with no error.
def type_of(datatype):
    d = str(datatype).lower()
    if d in ('real', 'integer'):
        return 'quantitative'
    if d in ('date', 'datetime'):
        return 'ordinal'
    return 'nominal'


# A field's derived attributes, computed once and reused across all blocks so the
# root metadata-record, the root column, the view column, and the column-instance
# all agree — mirrors wire_datasource.py's derive_field.
def derive_field(name, datatype, role, ordinal):
    is_measure = role == 'measure'
    field_type = type_of(datatype)
    # Spatial fields aggregate with Collect (a geometry union), not Sum/Count.
    aggregation = 'Collect' if datatype == 'spatial' else ('Sum' if is_measure else 'Count')
    return {
        'name': name,
        'datatype': datatype,
        'role': role,
        'type': field_type,
        'ordinal': ordinal,
        'aggregation': aggregation,
        'localName': f'[{name}]',
        'derivation': 'Sum' if is_measure else 'None',
        'instanceName': f'[sum:{name}:qk]' if is_measure else f'[none:{name}:nk]',
    }
