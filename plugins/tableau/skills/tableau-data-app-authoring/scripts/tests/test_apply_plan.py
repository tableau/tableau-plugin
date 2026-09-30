"""
Regression coverage for apply_plan.py, the Python port of apply-plan.mjs.

Every scenario here was verified byte-for-byte (stdout, stderr, exit code, and
resulting file tree) against the original Node script before the .mjs was
removed — see the PR description for how that parity check was done. These
tests exercise the CLI contract directly (subprocess), matching how SKILL.md
invokes the script, and no longer depend on Node being available.
"""

import json
import os
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'apply_plan.py')


def run_apply_plan(unzip_dir, plan_path):
    return subprocess.run([sys.executable, SCRIPT, unzip_dir, plan_path], capture_output=True, text=True)


def write_plan(tmp_path, plan):
    plan_path = tmp_path / 'plan.json'
    plan_path.write_text(json.dumps(plan))
    return str(plan_path)


def make_scaffold(tmp_path):
    app_dir = tmp_path / 'Data App Name'
    pkg_dir = app_dir / 'Packages' / 'com.tableau.mcp.TODO-MANIFEST-ID'
    pkg_dir.mkdir(parents=True)
    (app_dir / 'Data App Name.twb').write_text(
        '<workbook><app-name>TODO App Name</app-name><worksheets></worksheets></workbook>'
    )
    (pkg_dir / 'manifest.json').write_text(
        '{"id":"TODO-MANIFEST-ID","name":"TODO App Name","author":"TODO Username via Tableau MCP"}'
    )


def happy_plan():
    return {
        "edits": [
            {"file": "Data App Name/Data App Name.twb", "replacements": [
                {"find": "TODO App Name", "replace": "Sales Demo"}
            ]},
            {"file": "Data App Name/Packages/com.tableau.mcp.TODO-MANIFEST-ID/manifest.json", "replacements": [
                {"find": "TODO-MANIFEST-ID", "replace": "abc123"},
                {"find": "TODO App Name", "replace": "Sales Demo"},
                {"find": "TODO Username via Tableau MCP", "replace": "jsong"}
            ]}
        ],
        "renames": [
            {"from": "Data App Name/Packages/com.tableau.mcp.TODO-MANIFEST-ID",
             "to": "Data App Name/Packages/com.tableau.mcp.abc123"},
            {"from": "Data App Name", "to": "Sales Demo"}
        ],
        "wiresDatasource": False
    }


def test_happy_path_edits_then_renames(tmp_path):
    make_scaffold(tmp_path)
    plan_path = write_plan(tmp_path, happy_plan())
    result = run_apply_plan(str(tmp_path), plan_path)

    assert result.returncode == 0
    final_root = str(tmp_path / 'Sales Demo')
    assert result.stdout.strip() == final_root

    twb = tmp_path / 'Sales Demo' / 'Data App Name.twb'
    assert twb.read_text() == '<workbook><app-name>Sales Demo</app-name><worksheets></worksheets></workbook>'

    manifest = tmp_path / 'Sales Demo' / 'Packages' / 'com.tableau.mcp.abc123' / 'manifest.json'
    assert manifest.read_text() == '{"id":"abc123","name":"Sales Demo","author":"jsong"}'

    assert '  edited  Data App Name/Data App Name.twb' in result.stderr
    assert '  renamed Data App Name -> Sales Demo' in result.stderr
    assert f'✓ Finalized workspace at {final_root}' in result.stderr


def test_occurrence_first_resolves_two_identical_anchors_in_sequence(tmp_path):
    (tmp_path / 'f.txt').write_text('first:TOKEN second:TOKEN')
    plan_path = write_plan(tmp_path, {
        "edits": [{"file": "f.txt", "replacements": [
            {"find": "TOKEN", "replace": "ONE", "occurrence": "first"},
            {"find": "TOKEN", "replace": "TWO"}
        ]}],
        "renames": [],
        "wiresDatasource": False
    })
    result = run_apply_plan(str(tmp_path), plan_path)

    assert result.returncode == 0
    assert (tmp_path / 'f.txt').read_text() == 'first:ONE second:TWO'


def test_rename_deepest_first_then_root_and_placeholder_check_follows_both_renames(tmp_path):
    base = tmp_path / 'Root' / 'Nested'
    base.mkdir(parents=True)
    (base / 'f.txt').write_text('TODO App Name')
    plan_path = write_plan(tmp_path, {
        "edits": [{"file": "Root/Nested/f.txt", "replacements": [{"find": "TODO App Name", "replace": "Sales Demo"}]}],
        "renames": [
            {"from": "Root/Nested", "to": "Root/Renamed"},
            {"from": "Root", "to": "FinalRoot"}
        ],
        "wiresDatasource": False
    })
    result = run_apply_plan(str(tmp_path), plan_path)

    assert result.returncode == 0
    assert result.stdout.strip() == str(tmp_path / 'FinalRoot')
    assert (tmp_path / 'FinalRoot' / 'Renamed' / 'f.txt').read_text() == 'Sales Demo'


def test_empty_plan_is_rejected(tmp_path):
    plan_path = write_plan(tmp_path, {"edits": [], "renames": [], "wiresDatasource": False})
    result = run_apply_plan(str(tmp_path), plan_path)

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ Plan has no edits or renames — did you pass the full postUnzip object?'


def test_missing_find_token_hard_fails(tmp_path):
    (tmp_path / 'f.txt').write_text('hello world')
    plan_path = write_plan(tmp_path, {
        "edits": [{"file": "f.txt", "replacements": [{"find": "NOPE", "replace": "x"}]}],
        "renames": [],
        "wiresDatasource": False
    })
    result = run_apply_plan(str(tmp_path), plan_path)

    assert result.returncode == 1
    assert result.stderr.strip() == '✗ Placeholder "NOPE" not found in f.txt — template/plan out of sync.'


def test_rename_escaping_unzip_dir_is_rejected(tmp_path):
    inner = tmp_path / 'inner'
    inner.mkdir()
    (inner / 'f.txt').write_text('hi')
    plan_path = write_plan(tmp_path, {
        "edits": [], "renames": [{"from": "inner", "to": "../evil"}], "wiresDatasource": False
    })
    result = run_apply_plan(str(tmp_path), plan_path)

    assert result.returncode == 1
    assert 'Plan path escapes the unzip directory: ../evil' in result.stderr


def test_rename_of_nonexistent_source_hard_fails(tmp_path):
    plan_path = write_plan(tmp_path, {
        "edits": [], "renames": [{"from": "does-not-exist", "to": "renamed"}], "wiresDatasource": False
    })
    result = run_apply_plan(str(tmp_path), plan_path)

    assert result.returncode == 1
    assert result.stderr.startswith('✗ Rename failed: does-not-exist -> renamed')


def test_residual_wiring_anchor_survives_finalize_when_wires_datasource(tmp_path):
    app_dir = tmp_path / 'App'
    app_dir.mkdir()
    (app_dir / 'App.twb').write_text('<workbook><name>TODO App Name</name><datasources /><worksheets></worksheets></workbook>')
    plan_path = write_plan(tmp_path, {
        "edits": [{"file": "App/App.twb", "replacements": [{"find": "TODO App Name", "replace": "Sales Demo"}]}],
        "renames": [],
        "wiresDatasource": True
    })
    result = run_apply_plan(str(tmp_path), plan_path)

    assert result.returncode == 1
    assert 'Residual placeholders after finalize' in result.stderr
    assert 'App/App.twb: "<datasources />"' in result.stderr


def test_residual_wiring_anchor_is_fine_when_wires_datasource_false(tmp_path):
    app_dir = tmp_path / 'App'
    app_dir.mkdir()
    (app_dir / 'App.twb').write_text('<workbook><name>TODO App Name</name><datasources /><worksheets></worksheets></workbook>')
    plan_path = write_plan(tmp_path, {
        "edits": [{"file": "App/App.twb", "replacements": [{"find": "TODO App Name", "replace": "Sales Demo"}]}],
        "renames": [],
        "wiresDatasource": False
    })
    result = run_apply_plan(str(tmp_path), plan_path)

    assert result.returncode == 0
