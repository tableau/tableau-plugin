"""
CLI-level coverage for wire_embedded_datasource.py's connector-dispatch layer
— behavior that isn't specific to any one connector (extension routing, the
"unsupported file type" error enumerating every registered extension).

Per-connector coverage lives in test_csv.py / test_excel.py / test_hyper.py /
test_ogrdirect.py; shared fixture helpers live in helpers.py.
"""

from helpers import run_wire, write_csv, write_twb


def test_unsupported_extension_lists_supported_types(tmp_path):
    twb_path = write_twb(tmp_path)
    src_path = write_csv(tmp_path, "a,b\n1,2\n", filename='players.txt')
    result = run_wire(twb_path, src_path)

    assert result.returncode == 1
    assert 'Unsupported file type' in result.stderr
    # message must enumerate every supported extension
    assert '.csv' in result.stderr
    assert '.xlsx' in result.stderr
    assert '.hyper' in result.stderr
    assert '.zip' in result.stderr
