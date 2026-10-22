from __future__ import annotations
import argparse
import getpass
import json
import sys
from pathlib import Path

from .core import CleanerError, PasswordNeeded, analyze, clean, read_pdf, save_new


def main() -> int:
    parser = argparse.ArgumentParser(description="Local PDF text-overlay cleaner.")
    parser.add_argument("input", nargs="?", type=Path, help="Input PDF; omit to open the desktop UI")
    parser.add_argument("-o", "--output", type=Path, help="New output PDF path; never overwrite an existing file")
    parser.add_argument("--text", default="Preview", help="Target text, case-insensitive; default Preview")
    parser.add_argument("--inspect", action="store_true", help="Analyze without producing a PDF")
    parser.add_argument("--report", type=Path, help="Save a new JSON report")
    parser.add_argument("--print-only", action="store_true",
                        help="Enable printing without removing overlays. All exports enable printing; restricted copies lose PDF security.")
    args = parser.parse_args()
    if args.input is None:
        if args.output or args.inspect or args.report or args.print_only:
            parser.error("An input path is required for command-line operations.")
        from .qt_app import main as gui_main
        gui_main()
        return 0
    if not args.inspect and args.output is None:
        parser.error("Use --inspect or provide --output.")
    if args.inspect and args.print_only:
        parser.error("--print-only creates an output and cannot be combined with --inspect.")
    try:
        if args.output and args.output.exists():
            raise CleanerError("Output already exists. Choose a new filename.")
        if args.report and args.report.exists():
            raise CleanerError("Report path already exists. Choose a new filename.")
        if args.report and args.output and args.report.resolve() == args.output.resolve():
            raise CleanerError("Report and PDF need different filenames.")
        data = read_pdf(args.input)
        operation = analyze if args.inspect else clean
        options = {} if args.inspect else {"remove_overlays": not args.print_only}
        try:
            result = operation(data, args.text, **options)
        except PasswordNeeded:
            result = operation(data, args.text, getpass.getpass("PDF opening password: "), **options)
        if args.inspect:
            report = result
        else:
            report = result.report
            save_new(args.output, result.pdf_bytes, args.input)
            report = dict(report, output_path=str(args.output))
        if args.report:
            save_new(args.report, json.dumps(report, indent=2).encode(), args.input)
        print(json.dumps(report, indent=2))
        return 3 if report.get("unsupported_pages") else 0
    except (CleanerError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    raise SystemExit(main())
