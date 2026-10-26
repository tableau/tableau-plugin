"""
Regression coverage for package_twbx.py's CLI contract (stdout, stderr, exit code,
resulting archive), invoked via subprocess the way SKILL.md runs it.
"""

import os
import subprocess
import sys
import zipfile

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'package_twbx.py')
PACKAGE = 'Packages/com.tableau.mcp.sales-demo'
TWB_WITH_XLS = ("<workbook><datasources><datasource><connection class='federated'><named-connections>"
                "<named-connection name='excel'><connection class='excel-direct' filename='Data/Datasources/Sample.xls'/>"
                "</named-connection></named-connections></connection></datasource></datasources></workbook>")


def twb_referencing(*paths):
    connections = ''.join(f"<connection class='textscan' directory='{os.path.dirname(p)}' "
                          f"filename='{os.path.basename(p)}'/>" for p in paths)
    return f'<workbook>{connections}</workbook>'


def run_package(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


def make_workspace(tmp_path, with_trex=True):
    workspace = tmp_path / 'Sales Demo'
    ext_dir = workspace / PACKAGE / 'extensions'
    src_dir = workspace / PACKAGE / 'content' / 'src'
    ext_dir.mkdir(parents=True)
    src_dir.mkdir(parents=True)
    (workspace / 'Sales Demo.twb').write_text('<workbook/>')
    if with_trex:
        (ext_dir / 'data-app.trex').write_text('<manifest/>')
    (workspace / PACKAGE / 'content' / 'index.html').write_text('<html/>')
    (src_dir / 'app.js').write_text('// app')
    return workspace


def add_template_dirs(workspace):
    (workspace / 'Data').mkdir()
    (workspace / 'Data' / '.gitkeep').write_text('')
    (workspace / 'Resources' / '.agents').mkdir(parents=True)
    (workspace / 'Resources' / '.agents' / 'README.md').write_text('# Resources/.agents/')


def names(twbx_path):
    with zipfile.ZipFile(twbx_path) as archive:
        return archive.namelist()


def test_packages_twb_first_and_packages_at_root(tmp_path):
    workspace = make_workspace(tmp_path)
    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    output = str(tmp_path / 'Sales Demo.twbx')
    assert result.stdout.strip() == output

    entries = names(output)
    assert entries[0] == 'Sales Demo.twb'
    assert not any(entry.startswith('Sales Demo/') for entry in entries)
    assert f'{PACKAGE}/extensions/data-app.trex' in entries
    assert f'{PACKAGE}/content/index.html' in entries
    assert f'{PACKAGE}/content/src/app.js' in entries
    assert '✓ Packaged Sales Demo.twb + Packages/' in result.stderr


def test_excludes_ds_store_and_macosx(tmp_path):
    workspace = make_workspace(tmp_path)
    (workspace / '.DS_Store').write_text('x')
    (workspace / 'Packages' / '.DS_Store').write_text('x')
    (workspace / PACKAGE / 'content' / 'src' / '.DS_Store').write_text('x')
    macosx = workspace / 'Packages' / '__MACOSX' / 'com.tableau.mcp.sales-demo'
    macosx.mkdir(parents=True)
    (macosx / '._app.js').write_text('x')

    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    entries = names(result.stdout.strip())
    assert not any('.DS_Store' in entry or '__MACOSX' in entry for entry in entries)
    assert f'{PACKAGE}/content/src/app.js' in entries


def test_packs_data_at_root(tmp_path):
    workspace = make_workspace(tmp_path)
    datasources = workspace / 'Data' / 'Datasources'
    datasources.mkdir(parents=True)
    (datasources / 'Sample.xls').write_bytes(b'\xd0\xcf\x11\xe0')
    (datasources / '.DS_Store').write_text('x')
    (workspace / 'Sales Demo.twb').write_text(TWB_WITH_XLS)

    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    entries = names(result.stdout.strip())
    assert entries[0] == 'Sales Demo.twb'
    assert 'Data/Datasources/Sample.xls' in entries
    assert f'{PACKAGE}/extensions/data-app.trex' in entries
    assert not any(entry.startswith('Sales Demo/') for entry in entries)
    assert not any('.DS_Store' in entry for entry in entries)
    with zipfile.ZipFile(result.stdout.strip()) as archive:
        assert archive.read('Data/Datasources/Sample.xls') == b'\xd0\xcf\x11\xe0'
    assert '✓ Packaged Sales Demo.twb + Packages/, Data/ into' in result.stderr


def test_template_data_dir_with_only_placeholder_is_not_packed(tmp_path):
    workspace = make_workspace(tmp_path)
    add_template_dirs(workspace)

    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    entries = names(result.stdout.strip())
    assert not any(entry.startswith('Data') for entry in entries)
    assert 'Resources/.agents/README.md' in entries
    assert '✓ Packaged Sales Demo.twb + Packages/, Resources/.agents/ into' in result.stderr


def test_fails_when_twb_references_missing_data_file(tmp_path):
    workspace = make_workspace(tmp_path)
    (workspace / 'Sales Demo.twb').write_text(TWB_WITH_XLS)

    result = run_package(str(workspace))

    assert result.returncode == 1
    assert '✗ Sales Demo.twb references files missing from the workspace' in result.stderr
    assert 'Data/Datasources/Sample.xls' in result.stderr
    assert not (tmp_path / 'Sales Demo.twbx').exists()


def test_packs_only_data_files_the_twb_references(tmp_path):
    workspace = make_workspace(tmp_path)
    datasources = workspace / 'Data' / 'Datasources'
    datasources.mkdir(parents=True)
    (datasources / 'Sample.xls').write_bytes(b'\xd0\xcf\x11\xe0')
    (datasources / 'credentials.json').write_text('{"token": "x"}')
    (workspace / 'Data' / 'Scratch').mkdir()
    (workspace / 'Data' / 'Scratch' / 'notes.txt').write_text('x')
    (workspace / 'Sales Demo.twb').write_text(TWB_WITH_XLS)

    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    entries = names(result.stdout.strip())
    assert 'Data/Datasources/Sample.xls' in entries
    assert not any(e.startswith('Data/Scratch') or 'credentials' in e for e in entries)


def test_checks_directory_plus_filename_connections(tmp_path):
    workspace = make_workspace(tmp_path)
    (workspace / 'Sales Demo.twb').write_text(
        "<workbook><datasources><datasource><connection class='federated'><named-connections>"
        "<named-connection name='csv'><connection class='textscan' directory='Data' filename='orders.csv'/>"
        "</named-connection></named-connections></connection></datasource></datasources></workbook>")

    result = run_package(str(workspace))

    assert result.returncode == 1
    assert 'Data/orders.csv' in result.stderr

    (workspace / 'Data').mkdir()
    (workspace / 'Data' / 'orders.csv').write_text('a,b\n1,2\n')
    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    assert 'Data/orders.csv' in names(result.stdout.strip())


def write_files(workspace, *rels):
    for rel in rels:
        (workspace / rel).parent.mkdir(parents=True, exist_ok=True)
        (workspace / rel).write_text('x')


def test_packs_a_pdf_referenced_by_origfilename(tmp_path):
    workspace = make_workspace(tmp_path)
    write_files(workspace, 'Data/Datasources/Calcs.pdf')
    (workspace / 'Sales Demo.twb').write_text(
        "<workbook><connection class='pdf' origfilename='Data/Datasources/Calcs.pdf'/></workbook>")

    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    assert 'Data/Datasources/Calcs.pdf' in names(result.stdout.strip())


def test_packs_shapefile_companions_and_fails_without_required_ones(tmp_path):
    workspace = make_workspace(tmp_path)
    (workspace / 'Sales Demo.twb').write_text(
        "<workbook><connection class='ogrdirect' directory='Data/Datasources' filename='polygons.shp'/></workbook>")
    write_files(workspace, *(f'Data/Datasources/polygons.{e}' for e in ('shp', 'dbf', 'prj')))

    result = run_package(str(workspace))

    assert result.returncode == 1
    assert 'Data/Datasources/polygons.shx' in result.stderr

    write_files(workspace, 'Data/Datasources/polygons.shx', 'Data/Datasources/other.prj')
    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    assert sorted(e for e in names(result.stdout.strip()) if e.startswith('Data/Datasources/') and not e.endswith('/')) == [
        f'Data/Datasources/polygons.{e}' for e in ('dbf', 'prj', 'shp', 'shx')]


def test_packs_schema_ini_next_to_a_text_file(tmp_path):
    workspace = make_workspace(tmp_path)
    write_files(workspace, 'Data/orders.csv', 'Data/Schema.ini')
    (workspace / 'Sales Demo.twb').write_text(twb_referencing('Data/orders.csv'))

    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    assert 'Data/Schema.ini' in names(result.stdout.strip())


def test_packs_only_agents_under_resources(tmp_path):
    workspace = make_workspace(tmp_path)
    agents = workspace / 'Resources' / '.agents'
    (agents / 'history').mkdir(parents=True)
    (agents / 'README.md').write_text('# agents')
    (agents / 'history' / 'spec.md').write_text('# old spec')
    (workspace / 'Resources' / 'scratch.md').write_text('scratch')

    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    entries = names(result.stdout.strip())
    assert 'Resources/.agents/README.md' in entries
    assert 'Resources/.agents/history/spec.md' in entries
    assert 'Resources/scratch.md' not in entries
    assert '✓ Packaged Sales Demo.twb + Packages/, Resources/.agents/ into' in result.stderr


def test_skips_hidden_entries_below_packed_dirs(tmp_path):
    workspace = make_workspace(tmp_path)
    content = workspace / PACKAGE / 'content'
    (content / '.git').mkdir()
    (content / '.git' / 'config').write_text('x')
    (content / '.env').write_text('SECRET=x')
    (content / '.DS_Store').write_text('x')
    (content / '.config' / 'gh').mkdir(parents=True)
    (content / '.config' / 'gh' / 'hosts.yml').write_text('token: x')
    data = workspace / 'Data'
    data.mkdir()
    (data / '.env').write_text('SECRET=x')
    agents = workspace / 'Resources' / '.agents'
    agents.mkdir(parents=True)
    (agents / 'README.md').write_text('# agents')
    (agents / '.env').write_text('SECRET=x')

    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    entries = names(result.stdout.strip())
    assert 'Resources/.agents/README.md' in entries
    assert not any(part.startswith('.') for entry in entries
                   for part in entry.removeprefix('Resources/.agents/').split('/'))
    assert not any(entry.startswith('Data') for entry in entries)
    assert '✓ Packaged Sales Demo.twb + Packages/, Resources/.agents/ into' in result.stderr


def test_skips_other_workspace_dirs(tmp_path):
    workspace = make_workspace(tmp_path)
    (workspace / 'node_modules' / 'pkg').mkdir(parents=True)
    (workspace / 'node_modules' / 'pkg' / 'index.js').write_text('//')

    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    entries = names(result.stdout.strip())
    assert not any(entry.startswith('node_modules') for entry in entries)
    assert not any(entry.startswith(('Data', 'Resources')) for entry in entries)


def test_explicit_output_overwrites_existing_file(tmp_path):
    workspace = make_workspace(tmp_path)
    output = tmp_path / 'out' / 'custom.twbx'
    output.parent.mkdir()
    output.write_text('stale, not a zip')

    result = run_package(str(workspace), str(output))

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(output)
    assert names(str(output))[0] == 'Sales Demo.twb'


def test_fails_without_twb(tmp_path):
    workspace = make_workspace(tmp_path)
    (workspace / 'Sales Demo.twb').unlink()

    result = run_package(str(workspace))

    assert result.returncode == 1
    assert result.stdout == ''
    assert '✗ Expected exactly one .twb at the workspace root, found 0' in result.stderr
    assert not (tmp_path / 'Sales Demo.twbx').exists()


def test_fails_with_multiple_twbs(tmp_path):
    workspace = make_workspace(tmp_path)
    (workspace / 'Other.twb').write_text('<workbook/>')

    result = run_package(str(workspace))

    assert result.returncode == 1
    assert '✗ Expected exactly one .twb at the workspace root, found 2' in result.stderr


def test_fails_without_packages_dir(tmp_path):
    workspace = tmp_path / 'Sales Demo'
    workspace.mkdir()
    (workspace / 'Sales Demo.twb').write_text('<workbook/>')

    result = run_package(str(workspace))

    assert result.returncode == 1
    assert '✗ Missing Packages/ directory' in result.stderr


def test_fails_without_trex(tmp_path):
    workspace = make_workspace(tmp_path, with_trex=False)

    result = run_package(str(workspace))

    assert result.returncode == 1
    assert '✗ No .trex under Packages/*/extensions/' in result.stderr
    assert 'Package directory contains no extension .trex files under extensions/' in result.stderr
    assert not (tmp_path / 'Sales Demo.twbx').exists()
