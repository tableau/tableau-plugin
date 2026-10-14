#!/usr/bin/env python3
"""
Package a finalized data-app workspace into a `.twbx`. Workspace shape:
  <App Name>/
    <App Name>.twb
    Packages/<package id>/manifest.json, extensions/*.trex, content/...

The archive holds the `.twb` (written first) and `Packages/` at its ROOT, never
nested under `<App Name>/` — nesting fails to open on publish with
`PackageValidationException: Package directory contains no extension .trex
files under extensions/`. OS cruft (`.DS_Store`, `__MACOSX`) is skipped.

Hard-fails unless the workspace root has exactly one `.twb`, a `Packages/` dir,
and at least one `.trex` under `Packages/*/extensions/`. Also hard-fails if a
package with a `.trex` has no `manifest.json`, or if its `requestedOrigins` isn't
one space-separated string of bare origins; Tableau silently ignores any other
shape.

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

# Scheme + host + optional port: no path, query, or trailing slash.
ORIGIN_RE = re.compile(r'^https?://[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*(?::\d{1,5})?$')


def die(message):
    print(f'✗ {message}', file=sys.stderr)
    sys.exit(1)


def check_manifest(path):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
    except Exception as error:
        die(f'Could not read/parse {path}: {error}')
    if not isinstance(manifest, dict):
        die(f'{path} must be a JSON object.')
    value = manifest.get('requestedOrigins', '')
    if not isinstance(value, str):
        die(f'{path}: requestedOrigins must be ONE space-separated string, e.g. '
            f'"https://api.example.com https://cdn.example.com" (got a {type(value).__name__}). '
            'Tableau ignores any other shape and blocks every external origin.')
    bad = [origin for origin in value.split() if not ORIGIN_RE.match(origin)]
    if bad:
        die(f'{path}: requestedOrigins entries must be bare origins (scheme + host, optional port; no '
            f'path, query, trailing slash, or commas), separated by spaces: {", ".join(bad)}')


def is_cruft(rel_path):
    return any(part.endswith('.DS_Store') or part.startswith('__MACOSX') for part in rel_path.split('/'))


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

    trexes = glob.glob(os.path.join(packages, '*', 'extensions', '*.trex'))
    if not trexes:
        die('No .trex under Packages/*/extensions/ — publish would fail with '
            '"Package directory contains no extension .trex files under extensions/".')

    for package in sorted({os.path.dirname(os.path.dirname(trex)) for trex in trexes}):
        manifest = os.path.join(package, 'manifest.json')
        if not os.path.isfile(manifest):
            die(f'Missing manifest.json in {package}. Every data app package needs one; '
                're-scaffold with scaffold-data-app rather than writing it by hand.')
        check_manifest(manifest)

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
