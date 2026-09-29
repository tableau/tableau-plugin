"""
Shared fixture helpers for wire_embedded_datasource.py's per-connector test
modules (test_cli.py, test_csv.py, test_excel.py, test_hyper.py,
test_ogrdirect.py). Each connector's own fixture builder (write_xlsx,
write_hyper, write_shapefile_zip, ...) lives in that connector's own test
file, mirroring the connectors/ package split.
"""

import json
import os
import subprocess
import sys

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'wire_embedded_datasource.py')

TWB_TEMPLATE = """<?xml version='1.0' encoding='utf-8' ?>
<workbook version='18.1'>
  <datasources />
  <worksheets>
    <worksheet name='Sheet 1'>
      <table>
        <view>
          <datasources />
        </view>
      </table>
    </worksheet>
  </worksheets>
</workbook>
"""


def run_wire(twb_path, csv_path, descriptor_path=None):
    args = [sys.executable, SCRIPT, twb_path, csv_path]
    if descriptor_path:
        args.append(descriptor_path)
    return subprocess.run(args, capture_output=True, text=True)


def write_twb(tmp_path, content=TWB_TEMPLATE, filename='App.twb'):
    path = tmp_path / filename
    path.write_text(content)
    return str(path)


def write_csv(tmp_path, content, filename='players.csv'):
    path = tmp_path / filename
    path.write_text(content)
    return str(path)


def write_descriptor(tmp_path, descriptor):
    path = tmp_path / 'descriptor.json'
    path.write_text(json.dumps(descriptor))
    return str(path)
