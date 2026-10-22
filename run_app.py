if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == "--pdf-worker":
        from preview_cleaner.worker import run
        raise SystemExit(run(sys.argv[2]))
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test":
        from preview_cleaner.qt_diagnostics import run
        raise SystemExit(run(sys.argv[2]))
    from preview_cleaner.qt_app import main
    raise SystemExit(main())
