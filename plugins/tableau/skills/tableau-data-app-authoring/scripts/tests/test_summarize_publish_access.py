"""
CLI coverage for summarize_publish_access.py: exact stdout per publish-workbook
result shape, invoked via subprocess the way SKILL.md runs it.
"""

import json
import os
import subprocess
import sys

import pytest

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'summarize_publish_access.py'
)

URL = 'https://10ax.online.tableau.com/#/site/mcp-test/views/SalesDemo/SalesDemo'
CONFIRMATION = f'Published "Sales Demo" — {URL}'
MISSING_HEADER = 'Some viewers may not be able to view this data app. Missing workbook permissions:'
NO_RULES = (
    'No permission rules were returned for this workbook. '
    'Viewers need View, Full Data Query, and API Access on the workbook.'
)
NOT_VERIFIED = (
    'Viewer access was not verified. Viewers need View, Full Data Query, and API Access on the workbook.'
)
NAMED_SOURCE = 'Viewers also need API Access on the published data source "Superstore".'
UNNAMED_SOURCE = 'Viewers also need API Access on the published data source.'
NOTE = 'Published successfully, but the workbook permission rules could not be retrieved.'


def run_summary(tmp_path, result, *args):
    path = tmp_path / 'publish.json'
    path.write_text(json.dumps(result))
    return subprocess.run([sys.executable, SCRIPT, str(path), *args], capture_output=True, text=True)


def published(**extra):
    return {
        'status': 'published',
        'data': {'id': 'wb-1', 'name': 'Sales Demo'},
        'url': URL,
        'warnings': [],
        **extra,
    }


def caps(**modes):
    return {'capability': [{'name': name, 'mode': mode} for name, mode in modes.items()]}


def user_rule(capabilities, uid='user-1'):
    return {'user': {'id': uid, 'name': 'alice'}, 'capabilities': capabilities}


def group_rule(capabilities, gid='group-1'):
    return {'group': {'id': gid, 'name': 'All Users'}, 'capabilities': capabilities}


ALL_ALLOWED = caps(Read='Allow', Connect='Allow', VizqlDataApiAccess='Allow', Write='Deny')


@pytest.mark.parametrize(
    'args,expected',
    [((), f'{CONFIRMATION}\n'), (('--published-datasource', 'Superstore'), f'{CONFIRMATION}\n{NAMED_SOURCE}\n')],
    ids=['no-option', 'named-source'],
)
def test_all_granted_prints_confirmation_and_optional_source_line(tmp_path, args, expected):
    result = run_summary(tmp_path, published(permissions=[group_rule(ALL_ALLOWED), user_rule(ALL_ALLOWED)]), *args)

    assert result.returncode == 0
    assert result.stdout == expected


@pytest.mark.parametrize(
    'permissions,bullets',
    [
        (
            [group_rule(ALL_ALLOWED), user_rule(caps(Read='Allow', Connect='Allow'))],
            ['- alice (user): API Access'],
        ),
        (
            [group_rule(caps(Read='Allow', Connect='Deny', VizqlDataApiAccess='Allow'))],
            ['- All Users (group): Full Data Query'],
        ),
        (
            [group_rule(caps(Read='Allow', Connect='Allow', VizqlDataApiAccess='Unspecified'))],
            ['- All Users (group): API Access'],
        ),
        (
            [group_rule({'capability': [{'name': 'Read', 'mode': 'Allow'}, {'name': 'Read', 'mode': 'Deny'}]})],
            ['- All Users (group): View, Full Data Query, API Access'],
        ),
        (
            [group_rule(caps(Read='Allow', Connect='Allow', AIAccess='Allow'))],
            ['- All Users (group): API Access'],
        ),
        (
            [
                {'group': {'id': 'group-9'}, 'capabilities': caps(Read='Allow')},
                {'user': {'id': 'user-9'}, 'capabilities': {}},
                {'capabilities': caps(Connect='Allow')},
            ],
            [
                '- Unnamed group: Full Data Query, API Access',
                '- Unnamed user: View, Full Data Query, API Access',
                '- Unnamed rule: View, API Access',
            ],
        ),
    ],
    ids=['one-rule-lacks-api', 'connect-denied', 'unspecified', 'allow-and-deny', 'aiaccess-only', 'unnamed'],
)
def test_missing_capabilities_listed_per_rule(tmp_path, permissions, bullets):
    result = run_summary(tmp_path, published(permissions=permissions))

    assert result.returncode == 0
    assert result.stdout == '\n'.join([CONFIRMATION, MISSING_HEADER, *bullets]) + '\n'
    assert 'group-' not in result.stdout and 'user-' not in result.stdout
    assert not any(raw in result.stdout for raw in ('Read', 'Connect', 'Vizql', 'AIAccess'))


def test_empty_permissions_reports_no_rules(tmp_path):
    result = run_summary(tmp_path, published(permissions=[]), '--published-datasource', 'Superstore')

    assert result.returncode == 0
    assert result.stdout == f'{CONFIRMATION}\n{NO_RULES}\n{NAMED_SOURCE}\n'


@pytest.mark.parametrize(
    'extra',
    [{'permissionsNote': NOTE}, {'permissionsNote': NOTE, 'permissions': [group_rule({})]}],
    ids=['note-only', 'note-wins'],
)
def test_permissions_note_reports_unverified_without_raw_note(tmp_path, extra):
    result = run_summary(tmp_path, published(**extra), '--published-datasource')

    assert result.returncode == 0
    assert result.stdout == f'{CONFIRMATION}\n{NOT_VERIFIED}\n{UNNAMED_SOURCE}\n'
    assert NOTE not in result.stdout


def test_personal_space_prints_confirmation_only(tmp_path):
    result = run_summary(tmp_path, published(), '--published-datasource', 'Superstore')

    assert result.returncode == 0
    assert result.stdout == f'{CONFIRMATION}\n'


def test_warnings_listed(tmp_path):
    result = run_summary(
        tmp_path,
        published(
            warnings=[{'severity': 'warning', 'message': 'Font not embedded', 'elementName': 'style'}],
            permissions=[group_rule(ALL_ALLOWED)],
        ),
    )

    assert result.returncode == 0
    assert result.stdout == f'{CONFIRMATION}\nWarning: Font not embedded\n'


def test_warning_without_message_falls_back_to_json(tmp_path):
    warning = {'severity': 'warning', 'elementName': 'style'}
    result = run_summary(tmp_path, published(warnings=[warning, 'Plain text', {'message': ''}]))

    assert result.returncode == 0
    assert result.stdout == (
        f'{CONFIRMATION}\nWarning: {json.dumps(warning)}\nWarning: Plain text\nWarning: {{"message": ""}}\n'
    )
    assert 'None' not in result.stdout


def test_quoted_names_are_escaped(tmp_path):
    result = run_summary(
        tmp_path,
        published(data={'id': 'wb-1', 'name': 'Q4 "Final"'}, permissions=[group_rule(ALL_ALLOWED)]),
        '--published-datasource',
        'Super\\"store"',
    )

    assert result.returncode == 0
    assert result.stdout == (
        f'Published "Q4 \\"Final\\"" — {URL}\n'
        'Viewers also need API Access on the published data source "Super\\\\\\"store\\"".\n'
    )


@pytest.mark.parametrize(
    'data,url,expected',
    [({'id': 'wb-1'}, URL, f'Published — {URL}'), ({'id': 'wb-1', 'name': 'Sales Demo'}, '', 'Published "Sales Demo"')],
    ids=['no-name', 'empty-url'],
)
def test_confirmation_line_without_name_or_url(tmp_path, data, url, expected):
    result = run_summary(tmp_path, {'status': 'published', 'data': data, 'url': url, 'warnings': []})

    assert result.returncode == 0
    assert result.stdout == f'{expected}\n'


def test_invalid_status_fails(tmp_path):
    result = run_summary(
        tmp_path,
        {'status': 'invalid', 'errors': [{'severity': 'error', 'message': 'bad', 'elementName': 'x'}], 'warnings': []},
    )

    assert result.returncode != 0
    assert result.stdout == ''
    assert 'errors/warnings verbatim' in result.stderr


def test_removed_option_is_rejected(tmp_path):
    removed = '--no-published-datasource'
    result = run_summary(tmp_path, published(), removed)

    assert result.returncode != 0
    assert result.stdout == ''
    assert f'Unexpected argument: {removed}' in result.stderr
