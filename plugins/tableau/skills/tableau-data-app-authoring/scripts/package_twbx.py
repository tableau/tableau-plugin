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
and at least one `.trex` under `Packages/*/extensions/`.

Output defaults to `<App Name>.twbx` next to the workspace dir; an existing
file is overwritten. Prints the output path on stdout.

Usage: python3 package_twbx.py <workspaceDir> [outputPath]
"""

import glob
import os
import sys
import zipfile


def die(message):
    print(f'✗ {message}', file=sys.stderr)
    sys.exit(1)


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

    if not glob.glob(os.path.join(packages, '*', 'extensions', '*.trex')):
        die('No .trex under Packages/*/extensions/ — publish would fail with '
            '"Package directory contains no extension .trex files under extensions/".')

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
