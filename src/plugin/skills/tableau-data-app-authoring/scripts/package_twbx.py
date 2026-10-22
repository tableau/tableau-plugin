#!/usr/bin/env python3
"""
Package a finalized data-app workspace into a `.twbx`. Workspace shape:
  <App Name>/
    <App Name>.twb
    Packages/<package id>/extensions/*.trex, content/...
    Data/...                (optional: embedded datasource files the .twb references)
    Resources/.agents/...   (optional: agent docs that travel with the workbook)

The archive holds the `.twb` (written first), `Packages/`, and any `Data/` and
`Resources/.agents/` at its ROOT, never nested under `<App Name>/` — nesting fails to open on publish with
`PackageValidationException: Package directory contains no extension .trex
files under extensions/`. Without `Data/`, a `.twb` that references an embedded
file by relative path publishes fine but has no data at runtime. Nothing else
under `Resources/` is packed. OS cruft (`.DS_Store`, `__MACOSX`) and any
file or dir whose name starts with `.` below those dirs are skipped; hidden
ones are listed on stderr as `  skipped <path> (<why>)`. Symlinked files and
dirs are followed.

Hard-fails unless the workspace root has exactly one `.twb`, a `Packages/` dir,
at least one `.trex` under `Packages/*/extensions/`, and every `Data/` file the
`.twb` references.

Output defaults to `<App Name>.twbx` next to the workspace dir; an existing
file is overwritten. Prints the output path on stdout.

Usage: python3 package_twbx.py <workspaceDir> [outputPath]
"""

import glob
import os
import sys
import xml.etree.ElementTree as ET
import zipfile

# Workspace-relative dirs copied into the archive root, in order. Packages/ is
# required (checked in main); the rest are packed only when present.
PACKED_DIRS = ('Packages', 'Data', 'Resources/.agents')

HIDDEN_REASON = "(hidden: names starting with '.' are not packed)"

# Connection attributes that hold a workbook-relative file path.
FILE_ATTRS = ('filename', 'dbname')


def die(message):
    print(f'✗ {message}', file=sys.stderr)
    sys.exit(1)


def is_cruft(rel_path):
    return any(part.endswith('.DS_Store') or part.startswith('__MACOSX') for part in rel_path.split('/'))


def is_hidden(rel_path, top):
    # Hidden below the packed dir only, so Resources/.agents itself still ships.
    below = rel_path[len(top):].strip('/')
    return any(part.startswith('.') for part in below.split('/') if part)


def missing_data_files(workspace, twb):
    try:
        root = ET.parse(os.path.join(workspace, twb)).getroot()
    except ET.ParseError as error:
        die(f'Could not parse {twb}: {error}')
    missing = set()
    for element in root.iter('connection'):
        for attr in FILE_ATTRS:
            path = element.get(attr, '').replace('\\', '/')
            if path.startswith('Data/') and not os.path.isfile(os.path.join(workspace, path)):
                missing.add(path)
    return sorted(missing)


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

    missing = missing_data_files(workspace, twb)
    if missing:
        die(f'{twb} references files missing from the workspace (no data at runtime): '
            + ', '.join(missing))

    output = os.path.abspath(argv[2]) if len(argv) == 3 else os.path.join(
        os.path.dirname(workspace), os.path.basename(workspace) + '.twbx')

    dirs_to_pack = [top for top in PACKED_DIRS if os.path.isdir(os.path.join(workspace, top))]

    # Paths are workspace-relative so nothing lands under an <App Name>/ prefix.
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(os.path.join(workspace, twb), twb)
        visited = set()
        for top in dirs_to_pack:
            for root, dirs, files in os.walk(os.path.join(workspace, top), followlinks=True):
                dirs.sort()
                rel_root = os.path.relpath(root, workspace).replace(os.sep, '/')
                real_root = os.path.realpath(root)
                if is_cruft(rel_root) or real_root in visited:
                    dirs[:] = []
                    continue
                visited.add(real_root)
                archive.write(root, rel_root)
                # Prune hidden dirs here so each is reported once, not per file inside.
                for name in list(dirs):
                    rel = f'{rel_root}/{name}'
                    if not is_cruft(rel) and is_hidden(rel, top):
                        print(f'  skipped {rel}/ {HIDDEN_REASON}', file=sys.stderr)
                        dirs.remove(name)
                for name in sorted(files):
                    rel = f'{rel_root}/{name}'
                    if is_cruft(rel):
                        continue
                    if is_hidden(rel, top):
                        print(f'  skipped {rel} {HIDDEN_REASON}', file=sys.stderr)
                        continue
                    archive.write(os.path.join(root, name), rel)

    packed = ', '.join(f'{top}/' for top in dirs_to_pack)
    print(f'✓ Packaged {twb} + {packed} into {output}', file=sys.stderr)
    print(output)


if __name__ == '__main__':
    main()
