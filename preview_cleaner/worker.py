"""Headless worker entry point. Never import or initialize Tk in this process."""
import json
import os
from pathlib import Path


def run(folder):
    root = Path(folder)
    with (root / 'events.jsonl').open('a', encoding='utf-8') as events:
        def send(message):
            events.write(json.dumps(message) + '\n')
            events.flush()
        try:
            # fd 0 also works in a windowed PyInstaller executable (sys.stdin is None).
            with os.fdopen(0, 'r', encoding='utf-8') as request:
                options = json.load(request)
            if options.get('operation', '').startswith('library_'):
                from .music_library import run_library
                result = run_library(options, root, send)
                (root / 'report.json').write_text(json.dumps(result), encoding='utf-8')
                send(['done'])
                return 0
            if options.get('operation') in ('inspect', 'thumbnail', 'join', 'split'):
                from .assembly import run_request
                result = run_request(options, root, send)
                (root / 'report.json').write_text(json.dumps(result), encoding='utf-8')
                send(['done'])
                return 0
            from .core import clean, read_pdf
            result = clean(read_pdf(root / 'input.pdf'), options['target'], options['password'],
                           remove_overlays=options['remove_overlays'],
                           progress=lambda phase, done, total: send(['progress', phase, done, total]))
            (root / 'output.pdf').write_bytes(result.pdf_bytes)
            (root / 'report.json').write_text(json.dumps(result.report), encoding='utf-8')
            send(['done'])
            return 0
        except Exception as exc:
            send(['error', str(exc)])
            return 1


if __name__ == '__main__':
    import sys
    raise SystemExit(run(sys.argv[1]))
