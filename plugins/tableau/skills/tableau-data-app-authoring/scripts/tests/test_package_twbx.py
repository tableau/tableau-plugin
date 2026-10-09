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
