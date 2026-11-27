"""Launch the local review app or verify the configured release."""

from argparse import ArgumentParser
from pathlib import Path

from .app import create_app
from .catalog import CatalogError, load_catalog


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--code-root", type=Path, required=True)
    parser.add_argument("--thesis-root", type=Path, required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--case-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--check-release", action="store_true")
    args = parser.parse_args()
    code_root = args.code_root.expanduser().resolve()
    thesis_root = args.thesis_root.expanduser().resolve()
    case_dir = args.case_dir.expanduser().resolve()
    if not (code_root / "Phase_1_Code_Development" / "steps_1_3" / "examples").is_dir():
        parser.error("--code-root must contain the Phase 1 application and examples")
    if not case_dir.is_dir():
        parser.error("--case-dir must be an existing output directory")
    if case_dir.is_relative_to(thesis_root):
        parser.error("Choose an app output directory outside the read-only thesis input tree")
    try:
        catalog = load_catalog(thesis_root, args.release)
    except CatalogError as exc:
        parser.error(str(exc))
    for warning in catalog.diagnostics:
        print(warning)
    if args.check_release:
        print(f"Verified {args.release}: {len(catalog.release['workbooks'])} workbook files, "
              f"{sum(map(len, catalog.tables.values()))} named-table contracts")
        return
    app = create_app(catalog, code_root, thesis_root, case_dir)
    app.run(host="127.0.0.1", port=args.port, debug=False)


if __name__ == "__main__":
    main()
