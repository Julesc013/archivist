"""Conventional, scriptable CLI plus a small optional prompt. No separate planner."""

from __future__ import annotations
import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from . import __version__
from .application import Application, diagnose_runtime
from .progress import ConsoleProgress
from .util import Problem, bytes_value, json_read, require, sizes


def parser():
    p = argparse.ArgumentParser(
        prog="archivist",
        description="Scan -> plan -> build -> copy -> verify/restore. Offline by default. No source deletion.",
        epilog="Global options --workspace PATH, --json and --quiet may appear before or after the command.",
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command")
    s = sub.add_parser("scan", help="Record a source; Windows defaults to required Everything")
    s.add_argument("root")
    s.add_argument("--label")
    s.add_argument("--source-id")
    s.add_argument("--backend", choices=["everything", "filesystem", "auto"])
    s.add_argument("--es")
    s.add_argument("--instance", default="1.5a")
    s.add_argument("--timeout", type=int, default=1800)
    s.add_argument("--hash-files", action="store_true")
    s.add_argument("--cross-mounts", action="store_true")
    s = sub.add_parser("import-efu", help="Import a frozen Everything EFU/CSV export")
    s.add_argument("input")
    s.add_argument("--root", required=True)
    s.add_argument("--label")
    s = sub.add_parser("list", help="List recorded objects")
    s.add_argument(
        "kind",
        choices=["sources", "scans", "plans", "destinations", "builds", "replicas", "history"],
    )
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--offset", type=int, default=0)
    s = sub.add_parser("browse", help="Inspect direct children of a recorded directory")
    s.add_argument("snapshot_id")
    s.add_argument("--node-id", type=int)
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--offset", type=int, default=0)
    s = sub.add_parser("types")
    s.add_argument("snapshot_id")
    s.add_argument("--limit", type=int, default=1000)
    s = sub.add_parser("issues")
    s.add_argument("snapshot_id")
    s.add_argument("--limit", type=int, default=1000)
    s = sub.add_parser("plan", help="Create an immutable directory-first proposal")
    s.add_argument("snapshots", nargs="+")
    s.add_argument("--label", default="Archive plan")
    s.add_argument("--minimum", type=bytes_value, default=10_000_000_000)
    s.add_argument("--target", type=bytes_value, default=100_000_000_000)
    s.add_argument("--maximum", type=bytes_value, default=200_000_000_000)
    s.add_argument("--codec", choices=["auto", "none", "zstd", "gzip"], default="auto")
    s.add_argument("--level", type=int, default=3)
    s.add_argument("--outer-depth", type=int, default=4)
    s.add_argument("--keep-whole", type=bytes_value, default=0)
    s.add_argument("--merge-below", type=bytes_value, default=0)
    s = sub.add_parser("packages")
    s.add_argument("plan_id")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--offset", type=int, default=0)
    s.add_argument("--query")
    s.add_argument("--kind", choices=["data", "directories"])
    s = sub.add_parser("members")
    s.add_argument("plan_id")
    s.add_argument("package_id")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--offset", type=int, default=0)
    s = sub.add_parser("edit", help="Create a revision from codec/merge/move JSON")
    s.add_argument("plan_id")
    s.add_argument(
        "--changes", required=True, help="JSON file with codec_changes, merge and/or move"
    )
    s = sub.add_parser("allocate", help="Read-only first-fit allocation")
    s.add_argument("plan_id")
    s.add_argument(
        "--media", required=True, help="JSON file listing id, capacity, reserve, occupied, max_file"
    )
    s.add_argument("--bundle", help="Use this checked build for measured encoded sizes")
    s = sub.add_parser("diff", help="Compare immutable plan memberships and encoding")
    s.add_argument("plan_id")
    s.add_argument("target_plan_id")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--offset", type=int, default=0)
    s = sub.add_parser(
        "revert", help="Create a new revision using an earlier plan; never mutate history"
    )
    s.add_argument("plan_id")
    s.add_argument("target_plan_id")
    s = sub.add_parser(
        "find", help="Search sealed archive manifests; outputs whole-package restore selection"
    )
    s.add_argument("bundle")
    s.add_argument("query")
    s.add_argument("--mode", choices=["substring", "subtree"], default="substring")
    s.add_argument("--limit", type=int, default=100)
    s.add_argument("--offset", type=int, default=0)
    s = sub.add_parser(
        "build", help="Build and decode-verify; resumes at verified package boundaries"
    )
    s.add_argument("plan_id")
    s.add_argument("--output", required=True)
    s.add_argument("--package", dest="packages", action="append")
    s.add_argument("--accept-exclusions", action="store_true")
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("dest", help="Register an explicitly chosen destination directory")
    s.add_argument("path")
    s.add_argument("--label", required=True)
    s.add_argument("--kind", choices=["disk", "ltfs"], default="disk")
    s.add_argument("--capacity", type=bytes_value)
    s.add_argument("--max-file", type=bytes_value)
    s.add_argument("--reserve", type=bytes_value, default=0)
    s.add_argument("--experimental", action="store_true")
    s = sub.add_parser("copy", help="Copy to a registered destination and read back")
    s.add_argument("bundle")
    s.add_argument("--destination", required=True)
    s.add_argument("--package", dest="packages", action="append")
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("verify", help="Verify receipts, encoded bytes and decoded contents")
    s.add_argument("bundle")
    s.add_argument("--package", dest="packages", action="append")
    s = sub.add_parser("restore", help="Restore into a NEW directory; no silent merging/overwrite")
    s.add_argument("bundle")
    s.add_argument("--output", required=True)
    s.add_argument("--package", dest="packages", action="append")
    s.add_argument("--permissions", action="store_true")
    s.add_argument("--yes", action="store_true")
    s = sub.add_parser("bind", help="Explicitly bind an imported source to its current root")
    s.add_argument("source_id")
    s.add_argument("root")
    s = sub.add_parser("sample", help="Read bounded source samples; settings are not changed")
    s.add_argument("plan_id")
    s.add_argument("package_id")
    s.add_argument("--max-bytes", type=bytes_value, default=32 * 1024 * 1024)
    s = sub.add_parser("export", help="Export a checked workspace; no source/archive payloads")
    s.add_argument("output")
    s = sub.add_parser("export-inventory", help="Generate an optional full gzip JSONL listing")
    s.add_argument("snapshot_id")
    s.add_argument("output")
    s = sub.add_parser("import", help="Import a .ap20 bundle into a NEW unbound workspace")
    s.add_argument("input")
    s.add_argument("--output", required=True)
    s = sub.add_parser(
        "migrate-v13", help="Read-only migration of old scans and supported plan membership"
    )
    s.add_argument("input")
    sub.add_parser("doctor", help="Report runtime and actual tool availability")
    sub.add_parser("status")
    s = sub.add_parser("gui", help="Start the local browser interface")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-browser", action="store_true")
    sub.add_parser("shell", help="Small guided prompt; accepts the normal commands")
    return p


def print_result(value, machine=False):
    if machine:
        print(json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False))
        return
    if isinstance(value, dict) and value.get("scope") == "CATALOGUE_SEARCH":
        for row in value["rows"]:
            print(
                f"{row['package_id']}  {row['kind']:9}  {sizes(row['size']):32}  {json.dumps(row['path'], ensure_ascii=False)}"
            )
        print(f"Displayed {len(value['rows'])}; matching members {value['total']}.")
        print("Whole-package selection:", " ".join(value["package_ids"]) or "(none)")
        print("Directory metadata:", value.get("metadata_completeness", "unknown"))
        if value.get("missing_metadata_package_ids"):
            print("Missing metadata packages:", " ".join(value["missing_metadata_package_ids"]))
        print("Manifest lookup only; payload contents have not been verified by this search.")
        print(value["restore_scope"])
        return
    if isinstance(value, dict) and "before_plan" in value and "after_plan" in value:
        print("Compare", value["before_plan"], "→", value["after_plan"])
        for row in value["rows"]:
            before = (
                f"{row['before_package'] or '-'} {row['before_codec'] or '-'}:{row['before_level']}"
            )
            after = (
                f"{row['after_package'] or '-'} {row['after_codec'] or '-'}:{row['after_level']}"
            )
            print(
                f"{row['change']:17} {before} → {after}  {json.dumps(row['path'], ensure_ascii=False)}"
            )
        print(f"Displayed {len(value['rows'])}; changed members {value['total']}.")
        return
    if isinstance(value, list):
        if not value:
            print("(none)")
            return
        for row in value:
            fields = []
            for k in ("id", "state", "backend", "label", "name", "path", "root"):
                if row.get(k) is not None:
                    fields.append(f"{k}={json.dumps(row[k], ensure_ascii=False)}")
            counts = row.get("counts")
            if isinstance(counts, dict):
                fields.append(
                    f"files={counts.get('files', counts.get('eligible_files', '?')):,}"
                    if isinstance(counts.get("files", counts.get("eligible_files")), int)
                    else ""
                )
            print("  ".join(fields) if fields else json.dumps(row, ensure_ascii=False))
        return
    if isinstance(value, dict) and "rows" in value:
        for row in value["rows"]:
            n = (
                row.get("total_bytes", 0)
                if row.get("kind") == "directory"
                else row.get("size", row.get("bytes", 0))
            )
            print(
                f"{str(row.get('id', '')):>9}  {row.get('kind', row.get('extension', '')):10}  {sizes(n):32}  {json.dumps(row.get('path', row.get('name', row.get('extension', ''))), ensure_ascii=False)}"
            )
        print(f"Displayed {len(value['rows'])}; total {value.get('total', '?')}.")
        return
    if (
        isinstance(value, dict)
        and isinstance(value.get("packages"), list)
        and value["packages"]
        and all(
            isinstance(row, dict)
            and {"id", "status", "codec", "logical_bytes", "file_count", "reason", "anchor"}
            <= row.keys()
            for row in value["packages"]
        )
    ):
        for row in value["packages"]:
            print(
                f"{row['id']}  {row['status']:9} {row['codec']:5} {sizes(row['logical_bytes']):32} {row['file_count']:8,} files  {row['reason']}  {row['anchor']}"
            )
        print(
            "Plan:", value.get("plan", {}).get("id", ""), "total packages:", value.get("total", "?")
        )
        return
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def execute(argv):
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument("--workspace")
    global_parser.add_argument("--json", action="store_true")
    global_parser.add_argument("--quiet", action="store_true")
    global_args, remaining = global_parser.parse_known_args(argv)
    p = parser()
    args = vars(p.parse_args(remaining))
    command = args.pop("command")
    if command is None:
        if sys.stdin.isatty():
            command = "shell"
        else:
            p.print_help()
            return
    if command == "doctor":
        result = diagnose_runtime(global_args.workspace)
        print_result(result, global_args.json)
        return result
    app = Application(global_args.workspace)
    if command == "shell":
        return shell(app, global_args.quiet)
    if command == "gui":
        from .web import serve

        return serve(app, port=args["port"], open_browser=not args["no_browser"])
    if command == "plan":
        names = (
            "minimum",
            "target",
            "maximum",
            "codec",
            "level",
            "outer_depth",
            "keep_whole",
            "merge_below",
        )
        args["policy"] = {k: args.pop(k) for k in names}
    elif command == "list":
        command = args.pop("kind")
    elif command == "edit":
        changes = json_read(Path(args.pop("changes")))
        require(isinstance(changes, dict), "CHANGES", "Changes must be a JSON object")
        require(set(changes) <= {"codec_changes", "merge", "move"}, "CHANGES", "Unknown edit field")
        args.update(changes)
        command = "revise"
    elif command == "allocate":
        args["media"] = json_read(Path(args["media"]))
    command = {
        "dest": "destination",
        "import-efu": "import_efu",
        "migrate-v13": "migrate",
        "export-inventory": "export_inventory",
        "diff": "plan_diff",
        "find": "recovery_find",
    }.get(command, command)
    yes = args.pop("yes", False)
    with ConsoleProgress(global_args.quiet) as progress:
        if command in ("build", "copy", "restore"):
            review = app.call("preflight_" + command, args, progress)
            if not yes:
                print_result(review)
                require(
                    sys.stdin.isatty(),
                    "CONFIRMATION",
                    "Noninteractive writes require --yes after reviewing the requested paths",
                )
                require(
                    input("Type YES to execute this exact operation: ").strip() == "YES",
                    "NOT_APPROVED",
                    "No write performed",
                )
            args["approval"] = review["approval"]
        result = app.call(command, args, progress)
    print_result(result, global_args.json)
    return result


def shell(app, quiet=False):
    print(f"Archivist {__version__}  |  {app.workspace}")
    print("scan -> plan -> build -> copy -> verify / restore")
    print("Commands: status  list scans  gui  help  quit.  Type any normal CLI command.")
    while True:
        try:
            line = input("archivist> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if line in ("quit", "exit", "q"):
            return
        if not line:
            continue
        if line == "help":
            parser().print_help()
            continue
        try:
            parts = shlex.split(line, posix=os.name != "nt")
            if os.name == "nt":
                parts = [
                    s[1:-1] if len(s) > 1 and s[0] == s[-1] and s[0] in ("'", '"') else s
                    for s in parts
                ]
            execute(["--workspace", str(app.workspace)] + (["--quiet"] if quiet else []) + parts)
        except SystemExit:
            pass
        except Exception as exc:
            print(f"{getattr(exc, 'code', type(exc).__name__)}: {exc}", file=sys.stderr)


def main(argv=None):
    try:
        # Older Windows consoles and redirected ASCII streams can still display
        # every result using reversible escapes for unrepresentable characters.
        # Machine JSON already escapes Unicode independently of terminal settings.
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(errors="backslashreplace")
        execute(sys.argv[1:] if argv is None else argv)
    except KeyboardInterrupt:
        print(
            "CANCELLED: operation interrupted; committed packages and partial evidence are retained.",
            file=sys.stderr,
        )
        raise SystemExit(130)
    except Exception as exc:
        data = (
            exc.record()
            if isinstance(exc, Problem)
            else {"code": type(exc).__name__, "message": str(exc)}
        )
        print(json.dumps({"error": data}, ensure_ascii=True), file=sys.stderr)
        raise SystemExit(2)
