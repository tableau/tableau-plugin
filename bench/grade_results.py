#!/usr/bin/env python3
"""
Grade bench run outputs against the reference fixtures in bench/fixtures/<ACxx>/
(a reference image -- dashboard.svg or sheet.svg -- and, where present, a reference
data.csv). A perfect match is NOT expected: chart/dashboard design choices are
subjective, so each run is judged by asking a model to compare the produced view's
image + underlying data to the reference and score whether it satisfies the same
analytical intent -- not diffed exactly.

For each completed run, the workbook it published is looked up in
bench/results/created_assets.jsonl (by test_id/model/rep), then queried directly via
the Tableau MCP server (get-workbook to find its most recently updated view -- ties
(common, since publishing stamps every sheet with the same timestamp) are broken by
keyword overlap with the task prompt -- then get-view-image/get-view-data for that
view's rendered image and underlying data). No LLM is involved in that lookup; only
the final grading step calls a model.

Usage:
  python3 bench/grade_results.py                      # grade every ungraded completed run
  python3 bench/grade_results.py --only AC01_cold
  python3 bench/grade_results.py --judge-model gpt-5.6-sol
  python3 bench/grade_results.py --regrade             # re-grade runs that already have a score
"""
import argparse
import base64
import json
import re
import statistics
import subprocess
from pathlib import Path

from mcp_client import McpStdioClient, load_tableau_server_config, result_text

ROOT = Path(__file__).resolve().parent
DEFAULT_PROMPTS_FILE = ROOT / "prompts.json"
DEFAULT_RESULTS_DIR = ROOT / "results"
DEFAULT_LEDGER = DEFAULT_RESULTS_DIR / "created_assets.jsonl"
FIXTURES_DIR = ROOT / "fixtures"
JUDGE_SCHEMA = ROOT / "judge_schema.json"
DATA_INLINE_LIMIT = 6000  # chars of CSV inlined into the judge prompt, each side


def fixture_dir_for_test(test_id):
    return FIXTURES_DIR / test_id.split("_")[0]


def find_reference(fixture_dir):
    image = next(
        (fixture_dir / n for n in ("dashboard.svg", "sheet.svg") if (fixture_dir / n).exists()),
        None,
    )
    data = fixture_dir / "data.csv"
    return image, (data if data.exists() else None)


def rasterize_svg(svg_path, out_png_path, size=1600):
    out_png_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["qlmanage", "-t", "-s", str(size), "-o", str(out_png_path.parent), str(svg_path)],
        capture_output=True, text=True, timeout=30,
    )
    produced = out_png_path.parent / f"{svg_path.name}.png"
    if produced.exists():
        produced.replace(out_png_path)
        return out_png_path
    return None


def load_ledger_by_run(ledger_path):
    by_run = {}
    if not ledger_path.exists():
        return by_run
    for line in ledger_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        entry = json.loads(line)
        key = (entry["test_id"], entry["model"], entry["rep"])
        by_run.setdefault(key, []).append(entry)
    return by_run


def _keywords(text):
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 4}


def _keyword_overlap_score(view_name, task_prompt):
    """Loose stem match (compare first 5 chars) so e.g. "Sub-Categories" in a prompt
    still matches a view named "Sub-Category ...ranking"."""
    name_words = _keywords(view_name)
    prompt_words = _keywords(task_prompt)
    return sum(1 for pw in prompt_words if any(nw[:5] == pw[:5] for nw in name_words))


_REFERENCE_SHEET_RE = re.compile(r"^[a-z]{1,4}\d{1,3}$", re.IGNORECASE)


def _is_reference_sheet(view_name):
    """Sheets bare-named like a test id (e.g. "AC01", "AC03") are pre-built
    verification sheets the benchmark author put in the shared template to check
    expected outcomes -- never something a model under test produces. Models have
    been observed hallucinating a link to one of these in their final message (see
    extract_view_hint), so a hint resolving to one of these names is not trusted."""
    return bool(_REFERENCE_SHEET_RE.match((view_name or "").strip()))


def _slugify(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def extract_view_hint(run_dir):
    """The model's own final message often links straight to the view it published,
    e.g. ".../views/<workbook-content-url>/<ViewName>" -- that's a far more reliable
    signal of "the view this run produced" than any name/timestamp heuristic, so it's
    tried first. Returns the last path segment of the last such link, or None."""
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        return None
    steps = json.loads(summary_path.read_text()).get("steps") or []
    if not steps:
        return None
    msg = steps[-1].get("final_message") or ""
    urls = [u.rstrip(").,]>\"'") for u in re.findall(r"https?://\S+", msg)]
    for url in reversed(urls):
        if "/views/" in url:
            return url.rsplit("/", 1)[-1]
    return None


def pick_produced_view(client, workbook_id, task_prompt=None, view_hint=None):
    """Best-effort: the view most likely produced by this run.

    1. If view_hint (see extract_view_hint) matches a view by name, and that view isn't
       a known reference/verification sheet, use it directly.
    2. Otherwise, Tableau stamps every sheet in a workbook with the same publish-batch
       timestamp, so "most recently updated" alone can't tell a newly authored sheet
       apart from a pre-existing one that just rode along in the same publish -- ties
       are broken by scoring each candidate's name against the task prompt's keywords.
       Known reference/verification sheets are excluded from this fallback outright
       (a hallucinated hint pointing at one is exactly the case this guards against).
    """
    res = client.call_tool("get-workbook", {"workbookId": workbook_id})
    if res.get("isError"):
        return None, result_text(res)
    data = json.loads(result_text(res))
    views = ((data.get("data") or {}).get("views") or {}).get("view") or []
    if not views:
        return None, "workbook has no views"

    if view_hint:
        hint_norm = _slugify(view_hint)
        hinted = next((v for v in views if _slugify(v.get("name")) == hint_norm), None)
        if hinted and not _is_reference_sheet(hinted.get("name")):
            return hinted, None

    views = [v for v in views if not _is_reference_sheet(v.get("name"))]
    if not views:
        return None, "workbook has no non-reference views"

    def ts(v):
        return v.get("updatedAt") or v.get("createdAt") or ""

    latest = max((ts(v) for v in views), default="")
    candidates = [v for v in views if ts(v) == latest]
    if len(candidates) > 1 and task_prompt:
        candidates.sort(key=lambda v: _keyword_overlap_score(v.get("name", ""), task_prompt), reverse=True)
    return candidates[0], None


def fetch_view_artifacts(client, view_id, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    image_path = data_path = None
    errors = []

    img_res = client.call_tool("get-view-image", {"viewId": view_id, "format": "PNG", "width": 1600})
    if img_res.get("isError"):
        errors.append(f"get-view-image: {result_text(img_res)}")
    else:
        for block in img_res.get("content") or []:
            if block.get("type") == "image":
                image_path = out_dir / "produced.png"
                image_path.write_bytes(base64.b64decode(block["data"]))
                break

    data_res = client.call_tool("get-view-data", {"viewId": view_id})
    if data_res.get("isError"):
        errors.append(f"get-view-data: {result_text(data_res)}")
    else:
        text = result_text(data_res)
        if text:
            data_path = out_dir / "produced_data.csv"
            data_path.write_text(text)

    return image_path, data_path, errors


def truncate(text, limit):
    if text is None:
        return None
    return text if len(text) <= limit else text[:limit] + f"\n...(truncated, {len(text)} chars total)"


def read_text_robust(path):
    """Fixture data.csv files are Tableau crosstab exports, typically UTF-16 with a BOM
    (not plain UTF-8 despite the .csv extension); produced data from get-view-data is
    plain UTF-8. Try both rather than assuming one."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "utf-8"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def build_judge_prompt(task_prompt, reference_data_path, produced_data_path, produced_view_name):
    ref_data_text = truncate(read_text_robust(reference_data_path), DATA_INLINE_LIMIT) if reference_data_path else None
    prod_data_text = truncate(read_text_robust(produced_data_path), DATA_INLINE_LIMIT) if produced_data_path else None

    parts = [
        "You are grading a Tableau authoring benchmark run. A perfect match is NOT "
        "expected -- chart and dashboard design choices are subjective. Judge whether "
        "the produced view satisfies the same analytical intent as the reference, not "
        "whether it looks identical.",
        "",
        f"Task prompt given to the model under test:\n{task_prompt!r}",
        "",
        f"Produced view being graded: {produced_view_name!r}",
        "",
        "Two images are attached in order: [1] the reference design, [2] the produced view. "
        "If only one image is attached, it is the produced view and no reference image was available.",
        "",
        "Reference data (expected underlying data/aggregation):",
        ref_data_text if ref_data_text else "(no reference data available)",
        "",
        "Produced data (what this run actually returned):",
        prod_data_text if prod_data_text else "(failed to fetch produced data)",
    ]
    return "\n".join(parts)


def _run_judge_once(cmd, out_path):
    out_path.unlink(missing_ok=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if out_path.exists():
        try:
            return json.loads(out_path.read_text()), None
        except json.JSONDecodeError:
            pass
    return None, {
        "error": "judge call failed or produced no structured output",
        "returncode": proc.returncode,
        "stderr": proc.stderr[-2000:],
    }


def run_judge(prompt, images, model, out_path):
    cmd = ["codex", "exec", "--json", "--skip-git-repo-check"]
    if model:
        cmd += ["-m", model]
    for img in images:
        cmd += ["-i", str(img)]
    cmd += ["--output-schema", str(JUDGE_SCHEMA), "-o", str(out_path)]
    cmd.append(prompt)

    result, err = _run_judge_once(cmd, out_path)
    if result is not None:
        return result
    # codex exec's connection to its backend is occasionally flaky (model-list refresh
    # / websocket 404s) independent of anything about this particular run -- one retry
    # clears most of those without masking a persistent failure.
    print(f"    judge call failed ({err['error']}), retrying once ...", flush=True)
    result, err = _run_judge_once(cmd, out_path)
    return result if result is not None else err


def grade_run(client, test, run_dir, model_label, rep, ledger_by_run, judge_model):
    grading_dir = run_dir / "grading"
    fixture_dir = fixture_dir_for_test(test["id"])
    ref_image_svg, ref_data = find_reference(fixture_dir)

    entries = ledger_by_run.get((test["id"], model_label, rep))
    if not entries:
        return {"skipped": "no published asset recorded for this run"}
    asset = entries[-1]
    workbook_id = asset.get("workbook_id")
    if not workbook_id:
        return {"skipped": "ledger entry has no workbook_id"}

    task_prompt = test["steps"][-1]["prompt"]
    view_hint = extract_view_hint(run_dir)
    view, view_err = pick_produced_view(client, workbook_id, task_prompt, view_hint)
    if not view:
        return {"skipped": f"could not resolve a view for workbook {workbook_id}: {view_err}"}

    image_path, data_path, fetch_errors = fetch_view_artifacts(client, view["id"], grading_dir)

    ref_image_png = None
    if ref_image_svg:
        ref_image_png = rasterize_svg(ref_image_svg, grading_dir / "reference.png")

    images = [p for p in (ref_image_png, image_path) if p]
    prompt = build_judge_prompt(task_prompt, ref_data, data_path, view["name"])

    judge_out_path = grading_dir / "judge_result.json"
    verdict = run_judge(prompt, images, judge_model, judge_out_path)
    verdict.update({
        "workbook_id": workbook_id,
        "view_id": view["id"],
        "view_name": view["name"],
        "reference_image": str(ref_image_svg) if ref_image_svg else None,
        "reference_data": str(ref_data) if ref_data else None,
        "produced_image": str(image_path) if image_path else None,
        "produced_data": str(data_path) if data_path else None,
        "fetch_errors": fetch_errors,
    })
    judge_out_path.write_text(json.dumps(verdict, indent=2))
    return verdict


def render_grading_report(all_verdicts, out_path):
    lines = ["# Grading report", ""]
    by_test = {}
    for v in all_verdicts:
        by_test.setdefault(v["test_id"], []).append(v)

    for test_id, verdicts in by_test.items():
        lines.append(f"## {test_id}")
        by_model = {}
        for v in verdicts:
            by_model.setdefault(v["model"], []).append(v)
        for model, vs in by_model.items():
            graded = [v for v in vs if "visual_match" in v]
            skipped = [v for v in vs if "skipped" in v]
            errored = [v for v in vs if "error" in v]
            lines.append(f"### model: {model} (n={len(vs)}, graded={len(graded)}, skipped={len(skipped)}, errors={len(errored)})")
            if graded:
                vm = statistics.mean(v["visual_match"] for v in graded)
                dm = statistics.mean(v["data_match"] for v in graded)
                lines.append(f"- visual_match mean: {vm:.2f}/5")
                lines.append(f"- data_match mean: {dm:.2f}/5")
                for v in graded:
                    lines.append(
                        f"  - run {v['rep']:02d}: visual={v['visual_match']}/5 "
                        f"({v['visual_rationale']}), data={v['data_match']}/5 ({v['data_rationale']})"
                    )
            for v in skipped:
                lines.append(f"- run {v['rep']:02d}: skipped — {v['skipped']}")
            for v in errored:
                lines.append(f"- run {v['rep']:02d}: error — {v['error']}")
        lines.append("")

    out_path.write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts-file", type=Path, default=DEFAULT_PROMPTS_FILE)
    ap.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS_DIR)
    ap.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    ap.add_argument("--only", help="Grade only the test with this id")
    ap.add_argument("--judge-model", help="Model to pass to the judge's `codex exec -m`")
    ap.add_argument("--regrade", action="store_true", help="Re-grade runs that already have a judge_result.json")
    ap.add_argument("--server-cmd", nargs="+", default=None)
    ap.add_argument("--server-cwd", default=None)
    args = ap.parse_args()

    spec = json.loads(args.prompts_file.read_text())
    tests_by_id = {t["id"]: t for t in spec["tests"]}
    if args.only:
        tests_by_id = {k: v for k, v in tests_by_id.items() if k == args.only}

    ledger_by_run = load_ledger_by_run(args.ledger)

    default_cmd, default_cwd, server_env = load_tableau_server_config()
    client = McpStdioClient(args.server_cmd or default_cmd, args.server_cwd or default_cwd, env=server_env)

    all_verdicts = []
    try:
        client.initialize()
        for test_id, test in tests_by_id.items():
            test_dir = args.results_dir / test_id
            if not test_dir.exists():
                continue
            for model_dir in sorted(test_dir.iterdir()):
                if not model_dir.is_dir():
                    continue
                for run_dir in sorted(model_dir.glob("run_*")):
                    summary_path = run_dir / "summary.json"
                    if not summary_path.exists():
                        continue
                    summary = json.loads(summary_path.read_text())
                    model_label = summary["model"]
                    rep = int(run_dir.name.split("_")[1])

                    judge_out_path = run_dir / "grading" / "judge_result.json"
                    if judge_out_path.exists() and not args.regrade:
                        verdict = json.loads(judge_out_path.read_text())
                    else:
                        print(f"[{test_id}] model={model_label} run {rep:02d}: grading ...", flush=True)
                        verdict = grade_run(client, test, run_dir, model_label, rep, ledger_by_run, args.judge_model)
                        print(f"[{test_id}] model={model_label} run {rep:02d}: {verdict.get('skipped') or verdict.get('error') or 'graded'}", flush=True)

                    verdict["test_id"] = test_id
                    verdict["model"] = model_label
                    verdict["rep"] = rep
                    all_verdicts.append(verdict)
    finally:
        client.close()

    report_path = args.results_dir / "grading_report.md"
    render_grading_report(all_verdicts, report_path)
    print(f"\nGrading report written to {report_path}")


if __name__ == "__main__":
    main()
