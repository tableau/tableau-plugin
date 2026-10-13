#!/usr/bin/env python3
"""
Package a finalized data-app workspace into a `.twbx`. Workspace shape:
  <App Name>/
    <App Name>.twb
    Packages/<package id>/extensions/*.trex, content/...

The archive holds the `.twb` (written first) and `Packages/` at its ROOT, never
nested under `<App Name>/` — nesting fails to open on publish with
`PackageValidationException: Package directory contains no extension .trex
files under extensions/`. OS cruft (`.DS_Store`, `__MACOSX`) is skipped.

Hard-fails unless the workspace root has exactly one `.twb`, a `Packages/` dir,
and at least one `.trex` under `Packages/*/extensions/`, or if a package
`manifest.json` declares `requestedOrigins` as anything but one space-separated
string (Tableau silently ignores other shapes).

Warns (never fails) about things that break or leak at runtime: external origins
referenced in content/ but not declared with declare_origins.py, dotfiles in
content/ (the package host 404s them), fetch() of package-relative paths (fails
in the null-origin sandbox), and secret-looking keys in content/.

Output defaults to `<App Name>.twbx` next to the workspace dir; an existing
file is overwritten. Prints the output path on stdout.

Usage: python3 package_twbx.py <workspaceDir> [outputPath]
"""

import glob
import json
import os
import re
import sys
import zipfile

ORIGIN_IN_CODE = re.compile(r'''https?://[A-Za-z0-9.-]+(?::\d+)?''')
# Namespace URIs and other identifiers that never become network requests.
NON_NETWORK_ORIGINS = {'http://www.w3.org', 'https://www.w3.org'}
RELATIVE_FETCH = re.compile(r'''fetch\(\s*['"`](?![A-Za-z][A-Za-z0-9+.-]*:)''')
# A secret-looking key assigned a long string literal (e.g. "SPOTIFY_CLIENT_SECRET": "…"), not `token = null`.
SECRET_KEY = re.compile(r'''[\w-]*(secret|token|api[_-]?key|password|passwd|private[_-]?key)['"]?\s*[:=]\s*['"][^'"\s]{8,}['"]''',
                        re.IGNORECASE)
CODE_EXTENSIONS = ('.js', '.mjs', '.html', '.htm', '.css')


def die(message):
    print(f'✗ {message}', file=sys.stderr)
    sys.exit(1)


def is_cruft(rel_path):
    return any(part.endswith('.DS_Store') or part.startswith('__MACOSX') for part in rel_path.split('/'))


def warn(message):
    print(f'⚠ {message}', file=sys.stderr)


def requested_origins(package_dir):
    path = os.path.join(package_dir, 'manifest.json')
    if not os.path.exists(path):
        return set()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except Exception as error:
        die(f'Could not read/parse {path}: {error}')
    value = manifest.get('requestedOrigins') if isinstance(manifest, dict) else None
    if value is None:
        return set()
    if not isinstance(value, str):
        die(f'{path}: requestedOrigins must be ONE space-separated string; Tableau ignores a '
            f'{type(value).__name__} and blocks every external origin. Fix it with declare_origins.py.')
    return {o.lower() for o in value.split()}


# Runtime problems a zip can't catch: undeclared external origins, unservable files, leaked secrets.
def preflight(packages):
    for package_dir in sorted(glob.glob(os.path.join(packages, '*'))):
        content = os.path.join(package_dir, 'content')
        if not os.path.isdir(content):
            continue
        declared = requested_origins(package_dir)
        undeclared, dotfiles, relative_fetch, secrets = {}, [], [], []
        for root, dirs, files in os.walk(content):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(root, name)
                rel = os.path.relpath(full, packages).replace(os.sep, '/')
                if is_cruft(rel):
                    continue
                if name.startswith('.'):
                    dotfiles.append(rel)
                # The vendored Extensions API library is Tableau's own code.
                if not name.endswith(CODE_EXTENSIONS) or name.startswith('tableau.extensions.'):
                    continue
                with open(full, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()
                for origin in ORIGIN_IN_CODE.findall(text):
                    origin = origin.lower()
                    if origin not in declared and origin not in NON_NETWORK_ORIGINS:
                        undeclared.setdefault(origin, rel)
                if RELATIVE_FETCH.search(text):
                    relative_fetch.append(rel)
                if SECRET_KEY.search(text):
                    secrets.append(rel)
        pkg = os.path.basename(package_dir)
        if undeclared:
            warn(f'{pkg}: content references origins not in requestedOrigins: ' +
                 ', '.join(f'{o} ({f})' for o, f in sorted(undeclared.items())) +
                 '. Requests, images, scripts, or styles from them are blocked by the CSP unless declared '
                 'with declare_origins.py (plain links that only navigate are fine).')
        if dotfiles:
            warn(f'{pkg}: dotfiles in content/ are not served (404): {", ".join(dotfiles)}.')
        if relative_fetch:
            warn(f'{pkg}: fetch() of a package-relative path in {", ".join(relative_fetch)} fails in the '
                 'sandbox (null origin, no CORS). Ship data/config as a .js file loaded with <script src>.')
        if secrets:
            warn(f'{pkg}: secret-looking keys in {", ".join(secrets)}. Anyone who can open or download '
                 'the workbook can read them; see Security best practices in SKILL.md.')


def main():
    argv = sys.argv
    if len(argv) < 2 or len(argv) > 3:
        die('Usage: python3 package_twbx.py <workspaceDir> [outputPath]')

    workspace = os.path.abspath(argv[1])
    if not os.path.isdir(workspace):
        die(f'Workspace directory not found: {workspace}')

    twbs = sorted(name for name in os.listdir(workspace)
                  if name.endswith('.twb') and os.path.isfile(os.path.join(workspace, name)))
    if len(twbs) != 1:
        die(f'Expected exactly one .twb at the workspace root, found {len(twbs)}: {workspace}')
    twb = twbs[0]

    packages = os.path.join(workspace, 'Packages')
    if not os.path.isdir(packages):
        die(f'Missing Packages/ directory in {workspace}')

    if not glob.glob(os.path.join(packages, '*', 'extensions', '*.trex')):
        die('No .trex under Packages/*/extensions/ — publish would fail with '
            '"Package directory contains no extension .trex files under extensions/".')

    preflight(packages)

    output = os.path.abspath(argv[2]) if len(argv) == 3 else os.path.join(
        os.path.dirname(workspace), os.path.basename(workspace) + '.twbx')

    # Paths are workspace-relative so nothing lands under an <App Name>/ prefix.
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(os.path.join(workspace, twb), twb)
        for root, dirs, files in os.walk(packages):
            dirs.sort()
            rel_root = os.path.relpath(root, workspace).replace(os.sep, '/')
            if is_cruft(rel_root):
                dirs[:] = []
                continue
            archive.write(root, rel_root)
            for name in sorted(files):
                rel = f'{rel_root}/{name}'
                if not is_cruft(rel):
                    archive.write(os.path.join(root, name), rel)

    print(f'✓ Packaged {twb} + Packages/ into {output}', file=sys.stderr)
    print(output)


if __name__ == '__main__':
    main()
