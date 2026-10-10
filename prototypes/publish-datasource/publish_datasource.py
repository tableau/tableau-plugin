#!/usr/bin/env python3
"""Prototype: publish a .tdsx/.hyper to Tableau through REST, without Desktop.

Mirrors the sequence the planned MCP `publish-datasource` tool would run:
sign in -> fileUploads (64 MB chunks) -> POST datasources (asJob) -> poll job ->
look up the published data source -> sign out.

Stdlib only. Reads TABLEAU_PAT_NAME / TABLEAU_PAT_SECRET from the environment or
from a .env file passed with --env-file. Never prints the secret.

Usage:
  python3 publish_datasource.py FILE --server URL --site SITE --project-id LUID \
      --name NAME [--description TEXT] [--overwrite] [--no-job] [--env-file PATH]
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from xml.sax.saxutils import quoteattr

CHUNK_BYTES = 64 * 1024 * 1024


def load_env_file(path: Path) -> None:
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def ssl_context() -> ssl.SSLContext:
    bundle = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    return ssl.create_default_context(cafile=bundle) if bundle else ssl.create_default_context()


class Rest:
    def __init__(self, server: str, version: str):
        self.base = f"{server.rstrip('/')}/api/{version}"
        self.token: str | None = None
        self.ctx = ssl_context()

    def call(self, method: str, path: str, *, body: bytes | None = None,
             content_type: str | None = None, params: dict | None = None,
             timeout: int = 600) -> dict:
        url = f"{self.base}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Accept", "application/json")
        if content_type:
            req.add_header("Content-Type", content_type)
        if self.token:
            req.add_header("X-Tableau-Auth", self.token)
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:2000]
            raise SystemExit(f"{method} {path} -> HTTP {err.code}\n{detail}") from None
        return json.loads(raw) if raw else {}


def multipart_mixed(parts: list[tuple[str, str | None, str, bytes]]) -> tuple[bytes, str]:
    """parts: (name, filename, content_type, data)."""
    boundary = uuid.uuid4().hex
    out = bytearray()
    for name, filename, ctype, data in parts:
        disp = f'name="{name}"' + (f'; filename="{filename}"' if filename else "")
        out += f"--{boundary}\r\nContent-Disposition: form-data; {disp}\r\n".encode()
        out += f"Content-Type: {ctype}\r\n\r\n".encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/mixed; boundary={boundary}"


def server_api_version(server: str) -> str:
    probe = Rest(server, "2.4")
    info = probe.call("GET", "/serverinfo")
    return info["serverInfo"]["restApiVersion"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--server", required=True)
    ap.add_argument("--site", required=True, help="site contentUrl")
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--description", default="")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--no-job", action="store_true", help="publish synchronously (asJob=false)")
    ap.add_argument("--job-timeout", type=int, default=900)
    ap.add_argument("--env-file", type=Path)
    args = ap.parse_args()

    if args.env_file:
        load_env_file(args.env_file)
    pat_name = os.environ.get("TABLEAU_PAT_NAME")
    pat_secret = os.environ.get("TABLEAU_PAT_SECRET")
    if not pat_name or not pat_secret:
        raise SystemExit("TABLEAU_PAT_NAME and TABLEAU_PAT_SECRET must be set")

    ext = args.file.suffix.lower().lstrip(".")
    if ext not in ("tdsx", "hyper"):
        raise SystemExit("file must be .tdsx or .hyper")
    size = args.file.stat().st_size
    timings: dict[str, float] = {}

    version = server_api_version(args.server)
    api = Rest(args.server, version)
    print(f"REST API {version}; file {args.file.name} ({size / 1e6:.1f} MB)")

    t0 = time.monotonic()
    signin = api.call("POST", "/auth/signin", content_type="application/json", body=json.dumps({
        "credentials": {
            "personalAccessTokenName": pat_name,
            "personalAccessTokenSecret": pat_secret,
            "site": {"contentUrl": args.site},
        }
    }).encode())
    api.token = signin["credentials"]["token"]
    site_id = signin["credentials"]["site"]["id"]

    try:
        upload_id = api.call("POST", f"/sites/{site_id}/fileUploads")["fileUpload"]["uploadSessionId"]
        t_up = time.monotonic()
        with args.file.open("rb") as fh:
            n = 0
            while chunk := fh.read(CHUNK_BYTES):
                n += 1
                body, ctype = multipart_mixed([
                    ("request_payload", None, "text/xml", b""),
                    ("tableau_file", args.file.name, "application/octet-stream", chunk),
                ])
                api.call("PUT", f"/sites/{site_id}/fileUploads/{upload_id}", body=body, content_type=ctype)
                print(f"  chunk {n}: {len(chunk) / 1e6:.1f} MB")
        timings["upload_s"] = time.monotonic() - t_up

        desc = f" description={quoteattr(args.description)}" if args.description else ""
        payload = (f"<tsRequest><datasource name={quoteattr(args.name)}{desc}>"
                   f"<project id={quoteattr(args.project_id)}/></datasource></tsRequest>").encode()
        body, ctype = multipart_mixed([("request_payload", None, "text/xml", payload)])
        as_job = not args.no_job
        t_pub = time.monotonic()
        resp = api.call("POST", f"/sites/{site_id}/datasources", body=body, content_type=ctype, params={
            "uploadSessionId": upload_id,
            "datasourceType": ext,
            "overwrite": str(args.overwrite).lower(),
            "asJob": str(as_job).lower(),
        })

        job_result = None
        if "job" in resp:
            job_id = resp["job"]["id"]
            print(f"publish job {job_id} queued")
            deadline = time.monotonic() + args.job_timeout
            delay = 2.0
            while True:
                job = api.call("GET", f"/sites/{site_id}/jobs/{job_id}")["job"]
                if job.get("completedAt"):
                    job_result = job
                    break
                if time.monotonic() > deadline:
                    print(json.dumps({"status": "pending", "jobId": job_id}, indent=2))
                    return 2
                time.sleep(delay)
                delay = min(delay * 1.5, 15)
            if str(job_result.get("finishCode")) != "0":
                print(json.dumps({"status": "failed", "job": job_result}, indent=2))
                return 1
        timings["publish_s"] = time.monotonic() - t_pub

        ds = resp.get("datasource")
        if ds is None:
            # Async publish: resolve by name within the project.
            found = api.call("GET", f"/sites/{site_id}/datasources", params={
                "filter": f"name:eq:{args.name}",
            }).get("datasources", {}).get("datasource", [])
            found = [d for d in found if d.get("project", {}).get("id") == args.project_id]
            ds = found[0] if found else None
        timings["total_s"] = time.monotonic() - t0

        print(json.dumps({
            "status": "published" if ds else "published-but-not-found",
            "datasource": ds and {
                "id": ds.get("id"), "name": ds.get("name"), "contentUrl": ds.get("contentUrl"),
                "project": ds.get("project"), "webpageUrl": ds.get("webpageUrl"),
            },
            "server": args.server, "siteContentUrl": args.site, "asJob": as_job,
            "jobResult": job_result, "timings": {k: round(v, 1) for k, v in timings.items()},
        }, indent=2))
        return 0
    finally:
        api.call("POST", "/auth/signout")


if __name__ == "__main__":
    sys.exit(main())
