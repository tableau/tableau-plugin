#!/usr/bin/env python3
"""
Package a finalized data-app workspace into a `.twbx`. Workspace shape:
  <App Name>/
    <App Name>.twb
    Packages/<package id>/extensions/*.trex, content/...
    Data/...                (optional: embedded datasource files the .twb references)
    Resources/.agents/...   (optional: agent docs that travel with the workbook)

The scaffold-data-app template ships `Data/` holding only a `.gitkeep`
placeholder and `Resources/.agents/README.md`.

The archive holds the `.twb` (written first), `Packages/`, and any `Data/` and
`Resources/.agents/` at its ROOT, never nested under `<App Name>/` — nesting fails to open on publish with
`PackageValidationException: Package directory contains no extension .trex
files under extensions/`. Without `Data/`, a `.twb` that references an embedded
file by relative path publishes fine but has no data at runtime. Nothing else
under `Resources/` is packed. A dir is packed only when it holds at least one
packed file, so a `Data/` with nothing but its `.gitkeep` is left out. OS cruft
(`.DS_Store`, `__MACOSX`) and `.gitkeep` placeholders are skipped silently; any
other file or dir whose name starts with `.` below those dirs is skipped and
listed on stderr as `  skipped <path> (<why>)`. Symlinked files and dirs are
followed.

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

# Keeps an otherwise-empty dir (the template's Data/) in git; never packed or reported.
PLACEHOLDER = '.gitkeep'

# Connection attributes that hold a workbook-relative file path. Excel and Hyper
# put the whole path in one (filename='Data/x.xlsx'); CSV, JSON, and shapefile
# split it (directory='Data' filename='x.csv').
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


# Walk one packed dir and return its (path, archive name) entries in walk order,
# reporting hidden skips on stderr. Dirs are kept only on the way to a packed
# file, so a dir left with no files (an empty Data/) isn't packed at all.
def collect_entries(workspace, top):
    entries = []  # (path, archive name, is_dir)
    visited = set()
    for root, dirs, files in os.walk(os.path.join(workspace, top), followlinks=True):
        dirs.sort()
        rel_root = os.path.relpath(root, workspace).replace(os.sep, '/')
        real_root = os.path.realpath(root)
        if is_cruft(rel_root) or real_root in visited:
            dirs[:] = []
            continue
        visited.add(real_root)
        entries.append((root, rel_root, True))
        # Prune hidden dirs here so each is reported once, not per file inside.
        for name in list(dirs):
            rel = f'{rel_root}/{name}'
            if not is_cruft(rel) and is_hidden(rel, top):
                print(f'  skipped {rel}/ {HIDDEN_REASON}', file=sys.stderr)
                dirs.remove(name)
        for name in sorted(files):
            rel = f'{rel_root}/{name}'
            if is_cruft(rel) or name == PLACEHOLDER:
                continue
            if is_hidden(rel, top):
                print(f'  skipped {rel} {HIDDEN_REASON}', file=sys.stderr)
                continue
            entries.append((os.path.join(root, name), rel, False))

    # Every dir that is an ancestor of a packed file.
    needed_dirs = {rel.rsplit('/', i)[0] for _, rel, is_dir in entries if not is_dir
                   for i in range(1, rel.count('/') + 1)}
    return [(path, rel) for path, rel, is_dir in entries if not is_dir or rel in needed_dirs]


def missing_data_files(workspace, twb):
    try:
        root = ET.parse(os.path.join(workspace, twb)).getroot()
    except ET.ParseError as error:
        die(f'Could not parse {twb}: {error}')
    missing = set()
    for element in root.iter('connection'):
        directory = element.get('directory', '').replace('\\', '/').rstrip('/')
        for attr in FILE_ATTRS:
            path = element.get(attr, '').replace('\\', '/')
            if attr == 'filename' and directory and path:
                path = f'{directory}/{path}'
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

    entries_by_top = {top: collect_entries(workspace, top)
                      for top in PACKED_DIRS if os.path.isdir(os.path.join(workspace, top))}
    dirs_to_pack = [top for top, entries in entries_by_top.items() if entries]

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
