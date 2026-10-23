#!/usr/bin/env python3
"""
Package a finalized data-app workspace into a `.twbx`. Workspace shape:
  <App Name>/
    <App Name>.twb
    Packages/<package id>/extensions/*.trex, content/...
    Data/...                (optional: files the .twb references)
    Resources/.agents/...   (optional: agent docs)

The archive holds the `.twb` (written first), `Packages/`, `Data/`, and
`Resources/.agents/` at its ROOT, never nested under `<App Name>/`: nesting fails
to open on publish with `PackageValidationException: Package directory contains
no extension .trex files under extensions/`.

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

PACKED_DIRS = ('Packages', 'Data', 'Resources/.agents')

FILE_PATH_ATTRS = ('filename', 'dbname')


def die(message):
    print(f'✗ {message}', file=sys.stderr)
    sys.exit(1)


def is_cruft(rel_path):
    return any(part.endswith('.DS_Store') or part.startswith('__MACOSX') for part in rel_path.split('/'))


def collect_entries(workspace, top, allowed=None):
    entries = []  # (path, archive name, is_dir)
    for root, dirs, files in os.walk(os.path.join(workspace, top)):
        dirs.sort()
        rel_root = os.path.relpath(root, workspace).replace(os.sep, '/')
        if is_cruft(rel_root):
            dirs[:] = []
            continue
        entries.append((root, rel_root, True))
        dirs[:] = [name for name in dirs if not name.startswith('.')]
        for name in sorted(files):
            rel = f'{rel_root}/{name}'
            if name.startswith('.') or is_cruft(rel) or (allowed is not None and rel not in allowed):
                continue
            entries.append((os.path.join(root, name), rel, False))

    ancestor_dirs = {rel.rsplit('/', i)[0] for _, rel, is_dir in entries if not is_dir
                     for i in range(1, rel.count('/') + 1)}
    return [(path, rel) for path, rel, is_dir in entries if not is_dir or rel in ancestor_dirs]


def referenced_data_files(workspace, twb):
    try:
        root = ET.parse(os.path.join(workspace, twb)).getroot()
    except ET.ParseError as error:
        die(f'Could not parse {twb}: {error}')
    referenced = set()
    for element in root.iter('connection'):
        directory = element.get('directory', '').replace('\\', '/').rstrip('/')
        for attr in FILE_PATH_ATTRS:
            path = element.get(attr, '').replace('\\', '/')
            if attr == 'filename' and directory and path:
                path = f'{directory}/{path}'
            if path.startswith('Data/'):
                referenced.add(path)
    return referenced


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

    referenced = referenced_data_files(workspace, twb)
    entries_by_top = {}
    for top in PACKED_DIRS:
        if os.path.isdir(os.path.join(workspace, top)):
            entries_by_top[top] = collect_entries(workspace, top, referenced if top == 'Data' else None)
    dirs_to_pack = [top for top, entries in entries_by_top.items() if entries]

    packed = {rel for entries in entries_by_top.values() for _, rel in entries}
    missing = sorted(referenced - packed)
    if missing:
        die(f'{twb} references files missing from the workspace (no data at runtime): '
            + ', '.join(missing))

    # Paths are workspace-relative so nothing lands under an <App Name>/ prefix.
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(os.path.join(workspace, twb), twb)
        for top in dirs_to_pack:
            for path, rel in entries_by_top[top]:
                archive.write(path, rel)

    packed = ', '.join(f'{top}/' for top in dirs_to_pack)
    print(f'✓ Packaged {twb} + {packed} into {output}', file=sys.stderr)
    print(output)


if __name__ == '__main__':
    main()
