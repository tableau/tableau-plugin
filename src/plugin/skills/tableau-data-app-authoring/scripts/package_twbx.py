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
`.twb` references, with the files its format needs alongside (e.g. a shapefile's
`.shx` and `.dbf`; `Schema.ini` next to a text file is packed when present).

Output defaults to `<App Name>.twbx` next to the workspace dir; an existing
file is overwritten. Prints the output path on stdout.

Usage: python3 package_twbx.py <workspaceDir> [outputPath]
"""

import glob
import os
import sys
import xml.etree.ElementTree as ET
import zipfile

from file_formats import format_for_connection

PACKED_DIRS = ('Packages', 'Data', 'Resources/.agents')

FILE_PATH_ATTRS = ('filename', 'dbname', 'origfilename')


def die(message):
    print(f'✗ {message}', file=sys.stderr)
    sys.exit(1)


def collect_entries(workspace, top, allowed=None):
    entries = []  # (path, archive name, is_dir)
    for root, dirs, files in os.walk(os.path.join(workspace, top)):
        dirs[:] = sorted(name for name in dirs if not name.startswith(('.', '__MACOSX')))
        rel_root = os.path.relpath(root, workspace).replace(os.sep, '/')
        entries.append((root, rel_root, True))
        for name in sorted(files):
            rel = f'{rel_root}/{name}'
            if name.startswith('.') or (allowed is not None and rel not in allowed):
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
            if not path.startswith('Data/'):
                continue
            referenced.add(path)
            file_format = format_for_connection(element.get('class'), path)
            if file_format:
                required, optional = file_format.companions(path)
                referenced.update(required)
                referenced.update(p for p in optional if os.path.isfile(os.path.join(workspace, p)))
    return referenced


def collect_packed_dirs(workspace, twb):
    referenced = referenced_data_files(workspace, twb)
    entries_by_top = {}
    for top in PACKED_DIRS:
        if os.path.isdir(os.path.join(workspace, top)):
            entries = collect_entries(workspace, top, referenced if top == 'Data' else None)
            if entries:
                entries_by_top[top] = entries

    packed = {rel for entries in entries_by_top.values() for _, rel in entries}
    missing = sorted(referenced - packed)
    if missing:
        die(f'{twb} references files missing from the workspace (no data at runtime): '
            + ', '.join(missing))
    return entries_by_top


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

    entries_by_top = collect_packed_dirs(workspace, twb)

    # Paths are workspace-relative so nothing lands under an <App Name>/ prefix.
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(os.path.join(workspace, twb), twb)
        for entries in entries_by_top.values():
            for path, rel in entries:
                archive.write(path, rel)

    print(f"✓ Packaged {twb} + {', '.join(top + '/' for top in entries_by_top)} into {output}", file=sys.stderr)
    print(output)


if __name__ == '__main__':
    main()
