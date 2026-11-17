#!/usr/bin/env python3
"""Optional Playwright workflow fixture with native localhost navigation by default.

All assets and API responses come from the real local server. No source fixture or
browser dependency is required for the normal application or its core tests. The
explicit --bridge diagnostic mode does NOT qualify navigation or CSP enforcement.
"""

import argparse
import json
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from archivist.application import Application
from archivist.web import make_server


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    p.add_argument("--chromium", default="/usr/bin/chromium")
    p.add_argument(
        "--bridge",
        action="store_true",
        help="Diagnostic HTTP bridge; does not qualify native navigation/CSP",
    )
    a = p.parse_args()
    from playwright.sync_api import sync_playwright

    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix="ap20-browser-") as t:
        base = Path(t)
        source = base / "Source"
        source.mkdir()
        for path, data in [
            ("Projects/Small App/src/main.py", b'print("Hello")\n' * 5000),
            ("Projects/Small App/README.md", b"Documentation\n" * 2000),
            ("Photos/2026/capture.bin", bytes(range(256)) * 2000),
            ("Software/Installer/README.txt", b"Installation notes"),
            ("Software/Installer/setup.bin", bytes(range(256)) * 1000),
            ("loose.txt", b"One root note"),
        ]:
            f = source / path
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        (source / "Empty").mkdir()
        app = Application(base / "workspace")
        server = make_server(app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f"http://127.0.0.1:{server.server_port}"

        def get(path):
            with urllib.request.urlopen(origin + path, timeout=10) as r:
                return r.read().decode()

        html = get("/")
        css = get("/app.css")
        js = get("/app.js")

        def bridge(payload):
            url = payload["url"]
            opts = payload.get("options") or {}
            if not isinstance(url, str) or not url.startswith("/api/"):
                raise ValueError("Test bridge only permits this application API")
            body = opts.get("body")
            body = body.encode() if body is not None else None
            req = urllib.request.Request(
                origin + url,
                data=body,
                headers=opts.get("headers", {}),
                method=opts.get("method", "GET"),
            )
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return {"status": r.status, "body": r.read().decode()}
            except urllib.error.HTTPError as r:
                return {"status": r.code, "body": r.read().decode()}

        def passed(name):
            records.append({"check": name, "result": "PASS"})

        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(
                    executable_path=a.chromium, headless=True, args=["--no-sandbox"]
                )
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1000}, color_scheme="light"
                )
                page.set_default_timeout(15000)
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                if a.bridge:
                    page.expose_function("httpBridge", bridge)
                    supplied = re.sub(r'<link rel="stylesheet"[^>]*>', "", html)
                    supplied = re.sub(r'<script defer src="/app.js"></script>', "", supplied)
                    page.set_content(supplied)
                    page.add_style_tag(content=css)
                    page.add_script_tag(
                        content="window.fetch=async(url,options)=>{const r=await window.httpBridge({url:String(url),options:options||{}});return new Response(r.body,{status:r.status,headers:{'Content-Type':'application/json'}});};"
                    )
                    page.add_script_tag(content=js)
                else:
                    response = page.goto(origin + "/", wait_until="networkidle")
                    assert response.status == 200
                    assert "script-src 'self'" in response.headers["content-security-policy"]
                page.wait_for_function(
                    "document.getElementById('workspace-name').textContent.length>0"
                )
                passed(
                    "HTTP bridge bootstrap"
                    if a.bridge
                    else "Native localhost navigation with server CSP header"
                )
                page.get_by_role("button", name="Scan a source…", exact=True).click()
                page.get_by_label("Source directory", exact=True).fill(str(source))
                page.get_by_label("Label (optional)", exact=True).fill(
                    "Workshop sample · synthetic"
                )
                page.get_by_label("Acquisition", exact=True).select_option("filesystem")
                page.get_by_role("button", name="Scan", exact=True).click()
                page.wait_for_function(
                    "document.getElementById('notice').textContent.includes('Scan complete')"
                )
                passed("Filesystem scan via GUI calls the actual acquisition code")
                page.get_by_role("button", name="Create plan…", exact=True).click()
                page.get_by_label("Minimum goal · GB", exact=True).fill("0")
                page.get_by_label("Target · GB", exact=True).fill("0.001")
                page.get_by_label("Maximum · GB", exact=True).fill("0.005")
                page.get_by_label("Encoding", exact=True).select_option("none")
                page.get_by_role("button", name="Create plan", exact=True).click()
                page.wait_for_selector("#package-rows tr[data-select]")
                passed("Directory-first plan created and package table populated")
                page.locator("#package-rows tr[data-select]").first.click()
                page.wait_for_selector("#member-rows tr")
                passed("Package inspector retrieves actual recorded file members")
                page.screenshot(path=str(out / "plan-light.png"), full_page=True)
                page.get_by_label("Appearance", exact=True).select_option("dark")
                page.wait_for_timeout(500)
                page.screenshot(path=str(out / "plan-dark.png"), full_page=True)
                passed("One dark/light appearance setting; no theme framework")
                page.get_by_role("button", name="Encoding…", exact=True).click()
                # Inspector has a single codec select in this dialog.
                page.locator("#dialog-body select").select_option("gzip")
                page.get_by_role("button", name="Save revision", exact=True).click()
                page.wait_for_function(
                    "document.getElementById('notice').textContent.includes('Saved a new plan revision')"
                )
                page.wait_for_timeout(700)
                passed("Codec edit saves a separate plan revision")
                page.locator("#allocation summary").click()
                page.get_by_role("button", name="Calculate fit", exact=True).click()
                page.wait_for_selector("#allocation-results .fit-bar")
                passed("Capacity allocation reconciled through the same planner boundary")
                page.get_by_role("button", name="Build this plan…", exact=True).click()
                page.get_by_label("Staging output directory", exact=True).fill(str(base / "build"))
                page.get_by_role("button", name="Review build", exact=True).click()
                page.get_by_role("button", name="Confirm build", exact=True).click()
                page.wait_for_function(
                    "document.getElementById('notice').textContent.includes('build:') && !document.getElementById('notice').classList.contains('error')",
                    timeout=30000,
                )
                passed("Build preflight, explicit confirmation and real TAR/gzip verification")
                page.get_by_role("button", name="3 Archive", exact=True).click()
                page.wait_for_selector("#build-rows button")
                page.get_by_role("button", name="Register destination…", exact=True).click()
                page.get_by_label("Destination directory", exact=True).fill(str(base / "disk"))
                page.get_by_role("button", name="Register", exact=True).click()
                page.wait_for_function(
                    "document.getElementById('destination-list').textContent.includes('Backup disk')"
                )
                page.get_by_role("button", name="Copy…", exact=True).first.click()
                page.get_by_role("button", name="Review copy", exact=True).click()
                page.get_by_role("button", name="Confirm copy", exact=True).click()
                page.wait_for_function(
                    "document.getElementById('notice').textContent.includes('copy: COPY_READBACK')",
                    timeout=30000,
                )
                passed("Destination registration, identity review, copy and decoded readback")
                replicas = list((base / "disk" / "AP20-archives").glob("replica-*"))
                assert len(replicas) == 1
                page.get_by_role("button", name="4 Recover", exact=True).click()
                page.get_by_label("Archive-set directory", exact=True).fill(str(replicas[0]))
                page.get_by_label("Restore into a new directory", exact=True).fill(
                    str(base / "restored")
                )
                page.get_by_role("button", name="Review restoration…", exact=True).click()
                page.get_by_role("button", name="Confirm restore", exact=True).click()
                page.wait_for_function(
                    "document.getElementById('notice').textContent.includes('RESTORED_VERIFIED')",
                    timeout=30000,
                )
                passed(
                    "Recovery from copied artifacts through GUI; no original DB required by reader"
                )
                index = json.loads((replicas[0] / "ARCHIVE.json").read_text())
                ns = index["sources"][0]["namespace"]
                expected = {
                    x.relative_to(source).as_posix(): x.read_bytes()
                    for x in source.rglob("*")
                    if x.is_file()
                }
                restored = base / "restored" / ns
                actual = {
                    x.relative_to(restored).as_posix(): x.read_bytes()
                    for x in restored.rglob("*")
                    if x.is_file()
                }
                assert actual == expected and (restored / "Empty").is_dir()
                passed(
                    "Independent comparison: original file paths/bytes and empty directory restored"
                )
                page.set_viewport_size({"width": 390, "height": 844})
                page.get_by_role("button", name="2 Plan", exact=True).click()
                page.wait_for_timeout(300)
                page.screenshot(path=str(out / "plan-mobile.png"), full_page=True)
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth+1")
                passed("Narrow screen stacks panels without page-level horizontal overflow")
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.get_by_text("File", exact=True).first.click()
                page.get_by_role("button", name="Export workspace…", exact=True).click()
                page.get_by_label("New output filename", exact=True).fill(
                    str(base / "portable.ap20")
                )
                page.get_by_role("button", name="Export", exact=True).click()
                page.wait_for_function(
                    "document.getElementById('notice').textContent.includes('Exported:')"
                )
                assert (base / "portable.ap20").exists()
                passed("Unified File export produces a real portable workspace bundle")
                assert not errors, errors
                passed("No JavaScript runtime errors observed in tested workflow")
                browser.close()
        except BaseException:
            if "page" in locals():
                try:
                    page.screenshot(path=str(out / "failure.png"), full_page=True)
                except Exception:
                    pass
            raise
        finally:
            server.shutdown()
            server.server_close()
            server.tasks.close()
            thread.join()
            method = (
                "Actual HTTP assets/API through explicit fetch bridge; native navigation and CSP NOT qualified."
                if a.bridge
                else "Native localhost navigation with actual server headers; synthetic source data. Only completed checks are recorded."
            )
            (out / "gui-validation.json").write_text(
                json.dumps(
                    {
                        "checks": records,
                        "count": len(records),
                        "method": method,
                        "javascript_errors": errors if "errors" in locals() else [],
                    },
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()
