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
    # The scaffold-data-app template ships Data/ with only a placeholder, plus the agent README.
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
    assert 'gitkeep' not in result.stderr
    assert '✓ Packaged Sales Demo.twb + Packages/, Resources/.agents/ into' in result.stderr


def test_placeholder_is_skipped_silently_next_to_data_files(tmp_path):
    workspace = make_workspace(tmp_path)
    add_template_dirs(workspace)
    (workspace / 'Data' / 'Datasources').mkdir()
    (workspace / 'Data' / 'Datasources' / 'Sample.xls').write_bytes(b'\xd0\xcf\x11\xe0')
    (workspace / 'Sales Demo.twb').write_text(TWB_WITH_XLS)

    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    entries = names(result.stdout.strip())
    assert 'Data/Datasources/Sample.xls' in entries
    assert not any('gitkeep' in entry for entry in entries)
    assert 'gitkeep' not in result.stderr
    assert '✓ Packaged Sales Demo.twb + Packages/, Data/, Resources/.agents/ into' in result.stderr


def test_dirs_without_packed_files_are_left_out(tmp_path):
    workspace = make_workspace(tmp_path)
    data = workspace / 'Data'
    (data / 'Datasources').mkdir(parents=True)
    (data / 'Datasources' / 'Sample.xls').write_bytes(b'\xd0\xcf\x11\xe0')
    (data / 'Extracts').mkdir()
    (data / 'Scratch').mkdir()
    (data / 'Scratch' / '.gitkeep').write_text('')
    (workspace / 'Sales Demo.twb').write_text(TWB_WITH_XLS)

    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    entries = names(result.stdout.strip())
    assert 'Data/' in entries
    assert 'Data/Datasources/' in entries
    assert 'Data/Datasources/Sample.xls' in entries
    assert not any(entry.startswith(('Data/Extracts', 'Data/Scratch')) for entry in entries)


def test_fails_when_twb_references_missing_data_file(tmp_path):
    workspace = make_workspace(tmp_path)
    (workspace / 'Sales Demo.twb').write_text(TWB_WITH_XLS)

    result = run_package(str(workspace))

    assert result.returncode == 1
    assert '✗ Sales Demo.twb references files missing from the workspace' in result.stderr
    assert 'Data/Datasources/Sample.xls' in result.stderr
    assert not (tmp_path / 'Sales Demo.twbx').exists()


def test_checks_directory_plus_filename_connections(tmp_path):
    # CSV, JSON, and shapefile connections split the path: directory='Data' filename='x.csv'.
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
    assert f"  skipped {PACKAGE}/content/.config/ (hidden: names starting with '.' are not packed)\n" in result.stderr
    assert f"  skipped {PACKAGE}/content/.env (hidden: " in result.stderr
    assert 'skipped Resources/.agents/.env' in result.stderr
    assert 'gh/hosts.yml' not in result.stderr
    assert '.DS_Store' not in result.stderr
    # Data/ held only a hidden file, so it's reported but Data/ itself isn't packed.
    assert 'skipped Data/.env' in result.stderr
    assert not any(entry.startswith('Data') for entry in entries)
    assert '✓ Packaged Sales Demo.twb + Packages/, Resources/.agents/ into' in result.stderr


def test_follows_symlinked_data_dir(tmp_path):
    workspace = make_workspace(tmp_path)
    shared = tmp_path / 'shared'
    shared.mkdir()
    (shared / 'Sample.xls').write_bytes(b'\xd0\xcf\x11\xe0')
    (workspace / 'Data').mkdir()
    (workspace / 'Data' / 'Datasources').symlink_to(shared, target_is_directory=True)
    (workspace / 'Data' / 'Datasources' / 'loop').symlink_to(workspace / 'Data', target_is_directory=True)
    (workspace / 'Sales Demo.twb').write_text(TWB_WITH_XLS)

    result = run_package(str(workspace))

    assert result.returncode == 0, result.stderr
    entries = names(result.stdout.strip())
    assert 'Data/Datasources/Sample.xls' in entries
    assert not any('/loop/' in entry for entry in entries)


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
