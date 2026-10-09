"""
Regression coverage for declare_origins.py's CLI contract (stdout, stderr, exit code,
resulting manifest.json), invoked via subprocess the way SKILL.md runs it.
"""

import json
import os
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'declare_origins.py')
PACKAGE = 'Packages/com.tableau.mcp.sales-demo'

TREX = """<?xml version="1.0" encoding="utf-8"?>
<manifest manifest-version="0.1" xmlns="http://www.tableau.com/xml/extension_manifest">
  <worksheet-extension id="com.tableau.mcp.sales-demo" extension-version="1.0.0">
    <name resource-id="name" />
    <author name="Tableau MCP" email="noreply@tableau.com" website="https://www.tableau.com" />
  </worksheet-extension>
  <resources>
    <resource id="name">
      <text locale="en_US">Sales Demo</text>
    </resource>
  </resources>
</manifest>
"""

API = 'https://api.example.com'
AUTH = 'https://auth.example.com'


def run(*args):
    return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)


def make_workspace(tmp_path, with_trex=True):
    workspace = tmp_path / 'Sales Demo'
    ext_dir = workspace / PACKAGE / 'extensions'
    ext_dir.mkdir(parents=True)
    if with_trex:
        (ext_dir / 'data-app.trex').write_text(TREX)
    return workspace


def write_allowed(tmp_path, origins, whole_result=False):
    path = tmp_path / 'allowed.json'
    payload = {'datappName': 'Sales Demo', 'allowedOrigins': origins} if whole_result else origins
    path.write_text(json.dumps(payload))
    return str(path)


def manifest(workspace):
    return json.loads((workspace / PACKAGE / 'manifest.json').read_text())


def test_creates_manifest_from_trex_with_space_separated_string(tmp_path):
    workspace = make_workspace(tmp_path)
    allowed = write_allowed(tmp_path, [API, AUTH])

    result = run(str(workspace), '--allowed', allowed, '--add', API, AUTH)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(workspace / PACKAGE / 'manifest.json')
    assert manifest(workspace) == {
        'id': 'com.tableau.mcp.sales-demo',
        'version': '1.0.0',
        'name': 'Sales Demo',
        'author': 'Tableau MCP',
        'requestedOrigins': f'{API} {AUTH}',
    }


def test_accepts_whole_scaffold_result_as_allow_list(tmp_path):
    workspace = make_workspace(tmp_path)
    allowed = write_allowed(tmp_path, [API + '/'], whole_result=True)

    result = run(str(workspace), '--allowed', allowed, '--add', API)

    assert result.returncode == 0, result.stderr
    assert manifest(workspace)['requestedOrigins'] == API


def test_later_add_merges_dedupes_and_keeps_other_keys(tmp_path):
    workspace = make_workspace(tmp_path)
    allowed = write_allowed(tmp_path, [API, AUTH])
    assert run(str(workspace), '--allowed', allowed, '--add', API).returncode == 0
    path = workspace / PACKAGE / 'manifest.json'
    data = json.loads(path.read_text())
    data['custom'] = 'kept'
    path.write_text(json.dumps(data))

    result = run(str(workspace), '--allowed', allowed, '--add', AUTH, API)

    assert result.returncode == 0, result.stderr
    assert manifest(workspace)['requestedOrigins'] == f'{API} {AUTH}'
    assert manifest(workspace)['custom'] == 'kept'


def test_rewrites_array_value_as_string(tmp_path):
    workspace = make_workspace(tmp_path)
    (workspace / PACKAGE / 'manifest.json').write_text(json.dumps({'id': 'x', 'requestedOrigins': [API]}))
    allowed = write_allowed(tmp_path, [AUTH])

    result = run(str(workspace), '--allowed', allowed, '--add', AUTH)

    assert result.returncode == 0, result.stderr
    assert 'JSON array' in result.stderr
    assert manifest(workspace) == {'id': 'x', 'requestedOrigins': f'{API} {AUTH}'}


def test_warns_about_ignored_allowed_origins_key(tmp_path):
    workspace = make_workspace(tmp_path)
    (workspace / PACKAGE / 'manifest.json').write_text(json.dumps({'id': 'x', 'allowedOrigins': API}))

    result = run(str(workspace), '--list')

    assert result.returncode == 0, result.stderr
    assert '"allowedOrigins" key, which Tableau ignores' in result.stderr


def test_remove_and_list(tmp_path):
    workspace = make_workspace(tmp_path)
    allowed = write_allowed(tmp_path, [API, AUTH])
    assert run(str(workspace), '--allowed', allowed, '--add', API, AUTH).returncode == 0

    removed = run(str(workspace), '--remove', AUTH)
    listed = run(str(workspace), '--list')

    assert removed.returncode == 0, removed.stderr
    assert listed.stdout.split() == [API]


def test_removing_last_origin_drops_the_key(tmp_path):
    workspace = make_workspace(tmp_path)
    allowed = write_allowed(tmp_path, [API])
    assert run(str(workspace), '--allowed', allowed, '--add', API).returncode == 0

    result = run(str(workspace), '--remove', API)

    assert result.returncode == 0, result.stderr
    assert 'requestedOrigins' not in manifest(workspace)


def test_rejects_origin_not_on_allow_list(tmp_path):
    workspace = make_workspace(tmp_path)
    allowed = write_allowed(tmp_path, [API])

    result = run(str(workspace), '--allowed', allowed, '--add', AUTH)

    assert result.returncode == 1
    assert 'Not on the site allow-list: https://auth.example.com' in result.stderr
    assert 'Extension Package Allowed Origins' in result.stderr
    assert not (workspace / PACKAGE / 'manifest.json').exists()


def test_add_requires_allow_list_or_unverified(tmp_path):
    workspace = make_workspace(tmp_path)

    refused = run(str(workspace), '--add', API)
    unverified = run(str(workspace), '--unverified', '--add', API)

    assert refused.returncode == 1
    assert '--allowed' in refused.stderr
    assert unverified.returncode == 0, unverified.stderr
    assert '--unverified' in unverified.stderr
    assert manifest(workspace)['requestedOrigins'] == API


def test_rejects_malformed_origins(tmp_path):
    workspace = make_workspace(tmp_path)
    allowed = write_allowed(tmp_path, [API])

    for bad in (API + '/', API + '/v1', 'api.example.com', 'https://api.example.com?x=1'):
        result = run(str(workspace), '--allowed', allowed, '--add', bad)
        assert result.returncode == 1, bad
        assert 'is not an origin' in result.stderr


def test_fails_without_trex(tmp_path):
    workspace = make_workspace(tmp_path, with_trex=False)

    result = run(str(workspace), '--list')

    assert result.returncode == 1
    assert 'No .trex' in result.stderr
