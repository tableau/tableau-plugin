"""
File formats `wire_datasource.py` can embed and `package_twbx.py` packs. Each
base class is one connection shape; to add a format, subclass the base with the
same shape and list it in `FILE_FORMATS`.
"""

import os


def bracket(name):
    return '[' + name.replace(']', ']]') + ']'


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


def extension_of(path):
    return os.path.splitext(path)[1].lower()


class FileFormat:
    format = None
    label = None
    connection_class = None
    extensions = ()

    def connection_children(self):
        return ''

    # (required, optional) workspace paths packed alongside `path`.
    @classmethod
    def companions(cls, path):
        return (), ()


class DirectoryFile(FileFormat):
    """Points at the file by `directory` + `filename`; the file is its own table."""

    def __init__(self, path, table):
        if table is not None:
            raise ValueError(f'"table" applies only to Excel, PDF, and Hyper files; a {self.label} file is its own table.')
        self.directory, self.filename = path.rsplit('/', 1)
        self.relation_name = self.filename
        self.relation_table = bracket(self.filename)

    def connection_attrs(self):
        return {'directory': self.directory, 'filename': self.filename, 'password': '', 'server': ''}


class TextFile(DirectoryFile):
    format = 'text'
    label = 'text'
    extensions = ('.csv', '.txt', '.tsv', '.tab')
    connection_class = 'textscan'

    def __init__(self, path, table):
        super().__init__(path, table)
        stem, extension = self.filename.rsplit('.', 1)
        self.relation_table = bracket(f'{stem}#{extension}')

    @classmethod
    def companions(cls, path):
        return (), (f'{os.path.dirname(path)}/Schema.ini',)


class JsonFile(DirectoryFile):
    format = 'json'
    label = 'JSON'
    extensions = ('.json',)
    connection_class = 'semistructpassivestore-direct'

    # Without a schema the server exposes no fields; {root} reads the top-level keys.
    def connection_children(self):
        return (f"<semistruct-schemas><semistruct-schema table='{esc(bracket(self.filename))}'>"
                "<map key='{root}' value='true' /></semistruct-schema></semistruct-schemas>")


class StatFile(DirectoryFile):
    format = 'statistical'
    label = 'statistical'
    extensions = ('.sas7bdat', '.sav', '.rda', '.rdata')
    connection_class = 'stat-direct'


class SpatialFile(DirectoryFile):
    format = 'spatial'
    label = 'spatial'
    extensions = ('.geojson', '.topojson', '.json', '.shp', '.tab', '.mif')
    connection_class = 'ogrdirect'
    COMPANIONS = {
        '.shp': (('.shx', '.dbf'), ('.prj', '.cpg', '.sbn', '.sbx', '.shp.xml')),
        '.tab': (('.map', '.dat', '.id'), ('.ind',)),
        '.mif': (('.mid',), ()),
    }

    @classmethod
    def companions(cls, path):
        stem, extension = os.path.splitext(path)
        required, optional = cls.COMPANIONS.get(extension.lower(), ((), ()))
        companion = lambda ext: path + '.xml' if ext == '.shp.xml' else stem + ext
        return tuple(map(companion, required)), tuple(map(companion, optional))


class ExcelReaderFile(FileFormat):
    """Points at the file by one path attribute; `table` names a sheet or a page table."""
    path_attr = 'filename'
    interpretation_mode = '0'
    table_hint = None

    def __init__(self, path, table):
        if not isinstance(table, str) or not table:
            raise ValueError(f'{self.label} datasources need "table": {self.table_hint}.')
        self.path = path
        self.relation_name = table
        self.relation_table = bracket(f'{table}$')

    def connection_attrs(self):
        return {'cleaning': 'no', 'compat': 'no', 'dataRefreshTime': '', self.path_attr: self.path,
                'interpretationMode': self.interpretation_mode, 'password': '', 'server': '', 'validate': 'no'}


class ExcelFile(ExcelReaderFile):
    format = 'excel'
    label = 'Excel'
    extensions = ('.xls', '.xlsx', '.xlsm')
    connection_class = 'excel-direct'
    table_hint = 'the name of the sheet to query'


class PdfFile(ExcelReaderFile):
    format = 'pdf'
    label = 'PDF'
    extensions = ('.pdf',)
    connection_class = 'pdf'
    path_attr = 'origfilename'
    interpretation_mode = '257'
    table_hint = 'the page table to query, e.g. "Page    1 Table  1"'

    def connection_attrs(self):
        return {**super().connection_attrs(), 'pgFrom': '', 'pgTo': ''}


class DatabaseFile(FileFormat):
    """Points at the file by `dbname`; `table` is `schema.table`."""
    default_table = None

    def __init__(self, path, table):
        table = self.default_table if table is None else table
        if not isinstance(table, str) or table.count('.') != 1 or not all(table.split('.')):
            raise ValueError(f'"table" for a {self.label} file must be "schema.table" (default "{self.default_table}").')
        self.path = path
        self.schema, self.table = table.split('.')
        self.relation_name = self.table
        self.relation_table = f'{bracket(self.schema)}.{bracket(self.table)}'


class HyperFile(DatabaseFile):
    format = 'hyper'
    label = 'Hyper'
    extensions = ('.hyper',)
    connection_class = 'hyper'
    default_table = 'Extract.Extract'

    def connection_attrs(self):
        return {'dbname': self.path, 'authentication': 'auth-none', 'default-settings': 'yes',
                'schema': self.schema, 'tablename': self.table, 'username': 'tableau_internal_user'}


FILE_FORMATS = (ExcelFile, TextFile, PdfFile, HyperFile, JsonFile, StatFile, SpatialFile)

FORMATS_BY_EXTENSION = {}
for _file_format in FILE_FORMATS:
    for _extension in _file_format.extensions:
        FORMATS_BY_EXTENSION.setdefault(_extension, []).append(_file_format)


def format_for(path, format_name=None):
    extension = extension_of(path)
    candidates = FORMATS_BY_EXTENSION.get(extension)
    if not candidates:
        raise ValueError(f'"file" must end in {", ".join(FORMATS_BY_EXTENSION)} (got "{path}").')
    options = ' or '.join(f'"{c.format}"' for c in candidates)
    if format_name is None:
        if len(candidates) > 1:
            raise ValueError(f'"{extension}" files need "format": {options}.')
        return candidates[0]
    for candidate in candidates:
        if candidate.format == format_name:
            return candidate
    raise ValueError(f'"format" for a "{extension}" file must be {options} (got "{format_name}").')


# The format that wrote a `<connection>` in the .twb, or None.
def format_for_connection(connection_class, path):
    return next((f for f in FORMATS_BY_EXTENSION.get(extension_of(path), ())
                 if f.connection_class == connection_class), None)
