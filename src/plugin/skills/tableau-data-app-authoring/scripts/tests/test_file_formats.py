"""
Each format's connection, relation, and companions, compared with the shapes
that published and queried on Tableau Server.
"""

import pytest

from file_formats import format_for, format_for_connection

D = 'Data/Datasources'


def source(file, table=None, format_name=None):
    return format_for(file, format_name)(file, table)


@pytest.mark.parametrize('file, table, format_name, connection_class, attrs, relation_name, relation_table', [
    (f'{D}/orders.csv', None, None, 'textscan',
     {'directory': D, 'filename': 'orders.csv', 'password': '', 'server': ''}, 'orders.csv', '[orders#csv]'),
    (f'{D}/orders.tab', None, 'text', 'textscan',
     {'directory': D, 'filename': 'orders.tab', 'password': '', 'server': ''}, 'orders.tab', '[orders#tab]'),
    (f'{D}/Calcs.json', None, 'json', 'semistructpassivestore-direct',
     {'directory': D, 'filename': 'Calcs.json', 'password': '', 'server': ''}, 'Calcs.json', '[Calcs.json]'),
    (f'{D}/Calcs.rdata', None, None, 'stat-direct',
     {'directory': D, 'filename': 'Calcs.rdata', 'password': '', 'server': ''}, 'Calcs.rdata', '[Calcs.rdata]'),
    (f'{D}/polygons.shp', None, None, 'ogrdirect',
     {'directory': D, 'filename': 'polygons.shp', 'password': '', 'server': ''}, 'polygons.shp', '[polygons.shp]'),
    (f'{D}/Sales.xlsx', 'Orders', None, 'excel-direct',
     {'cleaning': 'no', 'compat': 'no', 'dataRefreshTime': '', 'filename': f'{D}/Sales.xlsx',
      'interpretationMode': '0', 'password': '', 'server': '', 'validate': 'no'}, 'Orders', '[Orders$]'),
    (f'{D}/Calcs.pdf', 'Page    1 Table  1', None, 'pdf',
     {'cleaning': 'no', 'compat': 'no', 'dataRefreshTime': '', 'origfilename': f'{D}/Calcs.pdf',
      'interpretationMode': '257', 'password': '', 'server': '', 'validate': 'no', 'pgFrom': '', 'pgTo': ''},
     'Page    1 Table  1', '[Page    1 Table  1$]'),
    (f'{D}/FullExtract.hyper', None, None, 'hyper',
     {'dbname': f'{D}/FullExtract.hyper', 'authentication': 'auth-none', 'default-settings': 'yes',
      'schema': 'Extract', 'tablename': 'Extract', 'username': 'tableau_internal_user'}, 'Extract', '[Extract].[Extract]'),
    (f'{D}/sales.hyper', 'public.Orders', None, 'hyper',
     {'dbname': f'{D}/sales.hyper', 'authentication': 'auth-none', 'default-settings': 'yes',
      'schema': 'public', 'tablename': 'Orders', 'username': 'tableau_internal_user'}, 'Orders', '[public].[Orders]'),
])
def test_connection_and_relation(file, table, format_name, connection_class, attrs, relation_name, relation_table):
    s = source(file, table, format_name)
    assert s.connection_class == connection_class
    assert s.connection_attrs() == attrs
    assert (s.relation_name, s.relation_table) == (relation_name, relation_table)


def test_json_writes_a_root_schema_and_others_write_no_children():
    assert source(f'{D}/Calcs.json', format_name='json').connection_children() == (
        "<semistruct-schemas><semistruct-schema table='[Calcs.json]'>"
        "<map key='{root}' value='true' /></semistruct-schema></semistruct-schemas>")
    assert source(f'{D}/orders.csv').connection_children() == ''


def test_ambiguous_extensions_need_a_format():
    with pytest.raises(ValueError, match=r'^"\.json" files need "format": "json" or "spatial"\.$'):
        format_for(f'{D}/places.json')
    with pytest.raises(ValueError, match=r'^"\.tab" files need "format": "text" or "spatial"\.$'):
        format_for(f'{D}/places.tab')
    assert format_for(f'{D}/places.json', 'spatial').connection_class == 'ogrdirect'
    with pytest.raises(ValueError, match=r'^"format" for a "\.csv" file must be "text" \(got "excel"\)\.$'):
        format_for(f'{D}/orders.csv', 'excel')


def test_table_rules():
    with pytest.raises(ValueError, match='PDF datasources need "table"'):
        source(f'{D}/Calcs.pdf')
    with pytest.raises(ValueError, match='a JSON file is its own table'):
        source(f'{D}/Calcs.json', 'x', 'json')
    with pytest.raises(ValueError, match=r'must be "schema.table" \(default "Extract.Extract"\)'):
        source(f'{D}/sales.hyper', 'Orders')


def test_companions():
    shp = format_for(f'{D}/polygons.shp')
    assert shp.companions(f'{D}/polygons.shp') == (
        (f'{D}/polygons.shx', f'{D}/polygons.dbf'),
        tuple(f'{D}/polygons{e}' for e in ('.prj', '.cpg', '.sbn', '.sbx', '.shp.xml')))
    assert format_for(f'{D}/roads.mif').companions(f'{D}/roads.mif') == ((f'{D}/roads.mid',), ())
    assert format_for(f'{D}/orders.csv').companions(f'{D}/orders.csv') == ((), (f'{D}/Schema.ini',))
    assert format_for(f'{D}/Calcs.pdf').companions(f'{D}/Calcs.pdf') == ((), ())


def test_format_for_connection_picks_by_class():
    assert format_for_connection('ogrdirect', f'{D}/roads.tab').format == 'spatial'
    assert format_for_connection('textscan', f'{D}/roads.tab').format == 'text'
    assert format_for_connection('sqlproxy', f'{D}/roads.tab') is None
