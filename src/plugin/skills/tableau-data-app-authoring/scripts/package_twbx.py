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
import shutil
import sys
import zipfile

AGENTS_DIR = '.agents'
AGENTS_README = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'assets', 'agents-README.md')
AGENTS_WARN_BYTES = 1024 * 1024


def die(message):
    print(f'✗ {message}', file=sys.stderr)
    sys.exit(1)


def is_cruft(rel_path):
    return any(part.endswith('.DS_Store') or part.startswith('__MACOSX') for part in rel_path.split('/'))


def ensure_agents_dir(workspace):
    """Create `.agents/README.md` from the bundled copy if missing; never overwrite."""
    readme = os.path.join(workspace, AGENTS_DIR, 'README.md')
    if not os.path.isfile(readme):
        os.makedirs(os.path.dirname(readme), exist_ok=True)
        shutil.copyfile(AGENTS_README, readme)
        print(f'• Created {AGENTS_DIR}/README.md (workspace had none)', file=sys.stderr)


def add_tree(archive, workspace, top):
    """Add `top` recursively under its workspace-relative path; returns bytes of files added."""
    total = 0
    for root, dirs, files in os.walk(top):
        dirs.sort()
        rel_root = os.path.relpath(root, workspace).replace(os.sep, '/')
        if is_cruft(rel_root):
            dirs[:] = []
            continue
        archive.write(root, rel_root)
        for name in sorted(files):
            rel = f'{rel_root}/{name}'
            if not is_cruft(rel):
                path = os.path.join(root, name)
                archive.write(path, rel)
                total += os.path.getsize(path)
    return total


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

    ensure_agents_dir(workspace)

    # Paths are workspace-relative so nothing lands under an <App Name>/ prefix.
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.write(os.path.join(workspace, twb), twb)
        add_tree(archive, workspace, packages)
        agents_bytes = add_tree(archive, workspace, os.path.join(workspace, AGENTS_DIR))

    if agents_bytes > AGENTS_WARN_BYTES:
        print(f'⚠ {AGENTS_DIR}/ is {agents_bytes / (1024 * 1024):.1f} MB — keep agent docs concise '
              'and text-only (no datasets, screenshots, or binaries).', file=sys.stderr)
    print(f'✓ Packaged {twb} + Packages/ + {AGENTS_DIR}/ into {output}', file=sys.stderr)
    print(output)


if __name__ == '__main__':
    main()
