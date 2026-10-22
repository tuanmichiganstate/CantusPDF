"""Standalone Prepare workspace development entry point."""
if __name__ == '__main__':
    from multiprocessing import freeze_support
    freeze_support()
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--pdf-worker':
        from preview_cleaner.worker import run
        raise SystemExit(run(sys.argv[2]))
    if len(sys.argv) == 4 and sys.argv[1] == '--smoke-test':
        from preview_cleaner.qt_smoke import run
        raise SystemExit(run(sys.argv[2], sys.argv[3]))
    from preview_cleaner.qt_preview import main
    raise SystemExit(main())
