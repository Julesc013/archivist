#!/usr/bin/env python3
"""Optional Playwright workflow fixture with native localhost navigation by default.

All assets and API responses come from the real local server under its CSP.
Playwright is a development-only dependency; the application does not require it.
Browser sandboxing stays enabled. A blocked launch is reported, never bypassed.
"""

import argparse
import importlib.metadata
import platform
import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from archivist.application import Application
from archivist.web import make_server


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", required=True)
    p.add_argument("--browser", choices=("chromium", "firefox", "webkit"), default="chromium")
    p.add_argument("--executable", help="Optional locally installed browser executable")
    p.add_argument(
        "--force-fallback-dialog", action="store_true", help="Qualify the non-native dialog path"
    )
    a = p.parse_args()
    from playwright.sync_api import sync_playwright

    out = Path(a.output)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    outcome = "FAILED"
    failure = None
    browser_version = None
    with tempfile.TemporaryDirectory(prefix="archivist-browser-") as t:
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

        def passed(name):
            records.append({"check": name, "result": "PASS"})

        try:
            with sync_playwright() as pw:
                launch = {"headless": True}
                if a.executable:
                    launch["executable_path"] = a.executable
                if a.browser == "chromium":
                    launch["chromium_sandbox"] = True
                browser = getattr(pw, a.browser).launch(**launch)
                browser_version = browser.version
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1000}, color_scheme="light"
                )
                page.set_default_timeout(15000)
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.add_init_script(
                    "window.__cspViolations=[]; document.addEventListener('securitypolicyviolation', function(e){window.__cspViolations.push({blockedURI:e.blockedURI,directive:e.effectiveDirective});});"
                )
                if a.force_fallback_dialog:
                    page.add_init_script(
                        "HTMLDialogElement.prototype.showModal=undefined; HTMLDialogElement.prototype.close=undefined;"
                    )
                response = page.goto(origin + "/", wait_until="networkidle")
                assert response.status == 200
                assert "script-src 'self'" in response.headers["content-security-policy"]
                page.wait_for_function(
                    "document.getElementById('workspace-name').textContent.length>0"
                )
                page.locator("#app-shell").wait_for(state="visible")
                page.locator("#compatibility").wait_for(state="hidden")
                passed("Native localhost navigation and capability bootstrap under the server CSP")
                page.get_by_role("button", name="Scan a source…", exact=True).focus()
                page.keyboard.press("Enter")
                page.locator("#dialog-submit").focus()
                page.keyboard.press("Tab")
                assert page.locator("#dialog-close").evaluate("e=>e===document.activeElement")
                page.keyboard.press("Shift+Tab")
                assert page.locator("#dialog-submit").evaluate("e=>e===document.activeElement")
                page.keyboard.press("Escape")
                assert not page.locator("#dialog").is_visible()
                assert page.locator("#new-scan").evaluate("e=>e===document.activeElement")
                passed(
                    "Modal keyboard focus cycle, Escape dismissal and focus return"
                    + (
                        " using fallback dialog"
                        if a.force_fallback_dialog
                        else " using native dialog"
                    )
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
                assert page.get_by_role(
                    "heading", name="Staging · retained archive set", exact=True
                ).is_visible()
                assert page.get_by_role(
                    "heading", name="Final destination · separate copy", exact=True
                ).is_visible()
                page.get_by_role("button", name="Confirm build", exact=True).click()
                page.wait_for_function(
                    "document.getElementById('notice').textContent.startsWith('build: COMPLETE') && !document.getElementById('notice').classList.contains('error')",
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
                assert page.get_by_role(
                    "heading", name="Final destination · this replica", exact=True
                ).is_visible()
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
                assert page.evaluate("window.__cspViolations.length") == 0
                page.evaluate(
                    "var s=document.createElement('script'); s.textContent='window.__unexpectedInlineExecution=true'; document.head.appendChild(s);"
                )
                assert page.evaluate("window.__unexpectedInlineExecution === undefined")
                page.wait_for_function(
                    "window.__cspViolations.some(function(v){return v.blockedURI==='inline';})"
                )
                passed("CSP rejects a deliberately injected inline script")
                context = browser.new_context(java_script_enabled=False)
                offline_page = context.new_page()
                offline_page.goto(origin + "/")
                assert offline_page.locator("#compatibility").is_visible()
                assert not offline_page.locator("#app-shell").is_visible()
                assert "command-line interface" in offline_page.locator("noscript").inner_text()
                context.close()
                passed("JavaScript-disabled page shows readable recovery and CLI guidance")
                context = browser.new_context()
                context.add_init_script("window.fetch=undefined;")
                limited_page = context.new_page()
                api_requests = []
                limited_page.on(
                    "request",
                    lambda request: (
                        api_requests.append(request.url) if "/api/" in request.url else None
                    ),
                )
                limited_page.goto(origin + "/", wait_until="networkidle")
                limited_page.wait_for_function(
                    "document.getElementById('compatibility-message').textContent.includes('Missing capabilities: Fetch')"
                )
                assert not limited_page.locator("#app-shell").is_visible()
                assert not api_requests, api_requests
                context.close()
                passed("Missing browser capability blocks the app before API submission")
                outcome = "PASS"
                browser.close()
        except BaseException as exc:
            failure = {"type": type(exc).__name__, "message": str(exc)[:8000]}
            if browser_version is None:
                outcome = "BLOCKED"
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
            method = "Native localhost navigation with actual assets and server headers; synthetic sources. Browser sandbox enabled. Only completed checks are recorded."
            (out / "gui-validation.json").write_text(
                json.dumps(
                    {
                        "status": outcome,
                        "browser": a.browser,
                        "browser_version": browser_version,
                        "playwright_version": importlib.metadata.version("playwright"),
                        "python": platform.python_version(),
                        "platform": platform.platform(),
                        "forced_dialog_fallback": a.force_fallback_dialog,
                        "failure": failure,
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
