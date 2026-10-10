#!/usr/bin/env python3
"""Repackage a .tdsx with a modified .tds, stripping server-binding elements.

Removes <repository-location> and the xml:base attribute so the package publishes
as new content instead of pointing at the data source it was downloaded from.
Optionally substitutes a different .tds (--tds) for the headless-generation test.

Usage: python3 repackage_tdsx.py IN.tdsx OUT.tdsx [--tds REPLACEMENT.tds]
"""

from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path


def strip_server_binding(xml: str) -> str:
    xml = re.sub(r"\s*<repository-location\b[^>]*/>", "", xml, count=1)
    return re.sub(r"\s+xml:base='[^']*'", "", xml, count=1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--tds", type=Path, help="use this .tds instead of the packaged one")
    args = ap.parse_args()

    with zipfile.ZipFile(args.src) as zin, \
         zipfile.ZipFile(args.dst, "w", zipfile.ZIP_DEFLATED) as zout:
        tds_entries = [i for i in zin.infolist() if i.filename.lower().endswith(".tds")]
        if len(tds_entries) != 1:
            raise SystemExit(f"expected one .tds in package, found {len(tds_entries)}")
        for info in zin.infolist():
            if info is tds_entries[0]:
                xml = (args.tds.read_text(encoding="utf-8") if args.tds
                       else zin.read(info).decode("utf-8"))
                zout.writestr(info.filename, strip_server_binding(xml))
            else:
                with zin.open(info) as src, zout.open(info.filename, "w") as dst:
                    while block := src.read(16 * 1024 * 1024):
                        dst.write(block)
    print(f"wrote {args.dst} ({args.dst.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
