"""Disposable headless workers with private files and bounded lifetime."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from time import monotonic

from .core import Result


class CleaningJob:
    def __init__(self, data: bytes, target: str, password: str, remove_overlays: bool,
                 timeout: float = 300, *, request_options=None):
        self.storage = TemporaryDirectory(prefix='preview-cleaner-')
        self.folder = Path(self.storage.name)
        self.closed = False
        self.started = monotonic()
        self.timeout = timeout
        self.process = None
        self.receiver = None
        self.buffer = b''
        try:
            request = json.dumps(request_options if request_options is not None else dict(
                target=target, password=password, remove_overlays=remove_overlays)).encode('utf-8')
            if len(request) > (4 * 1048576 if request_options is not None else 4096):
                raise ValueError('Overlay text or password is too long.')
            (self.folder / 'input.pdf').write_bytes(data)
            self.receiver = (self.folder / 'events.jsonl').open('w+b', buffering=0)
            if getattr(sys, 'frozen', False):
                command = [sys.executable, '--pdf-worker', str(self.folder)]
            else:
                command = [sys.executable, '-m', 'preview_cleaner.worker', str(self.folder)]
            environment = os.environ.copy()
            if not getattr(sys, 'frozen', False):
                # Work from any current directory, without importing a GUI main module.
                environment['PYTHONPATH'] = str(Path(__file__).resolve().parent.parent)
            self.process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                env=environment,
                # Python 3.12 requires this to use posix_spawn on macOS. Python-opened
                # descriptors are non-inheritable; no pass_fds/preexec_fn/cwd are used.
                # Avoid forked Cocoa state and inherited graphical signal handlers.
                close_fds=sys.platform != 'darwin',
            )
            try:
                self.process.stdin.write(request)
                self.process.stdin.close()
            except BrokenPipeError:
                # poll() reports the failed startup, without leaking the request.
                self.process.stdin.close()
        except Exception:
            self.close()
            raise

    def poll(self):
        if self.closed:
            return []
        if monotonic() - self.started > self.timeout:
            self.close()
            return [('error', 'Processing exceeded five minutes. Try a smaller PDF.')]
        messages = []
        # Snapshot exit first, then drain: a terminal event written before exit must
        # be consumed before reporting an unexpected exit.
        exited = self.process.poll() is not None
        self.buffer += self.receiver.read(65536)
        lines = self.buffer.split(b'\n')
        self.buffer = lines.pop()
        for line in lines:
            message = json.loads(line)
            if message[0] == 'done':
                try:
                    result = self.read_result()
                    return messages + [('done', result)]
                finally:
                    self.close(completed=True)
            if message[0] == 'error':
                self.close(completed=True)
                return messages + [tuple(message)]
            messages.append(tuple(message))
        if exited and self.receiver.tell() == (self.folder / 'events.jsonl').stat().st_size:
            self.close()
            return messages + [('error', 'The PDF worker exited unexpectedly.')]
        return messages

    def read_result(self):
        return Result((self.folder / 'output.pdf').read_bytes(),
                      json.loads((self.folder / 'report.json').read_text(encoding='utf-8')))

    def close(self, completed=False):
        if self.closed:
            return
        self.closed = True
        if self.process is not None:
            if completed:
                try:
                    self.process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    pass
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            if self.process.stdin is not None:
                self.process.stdin.close()
        if self.receiver is not None:
            self.receiver.close()
        self.storage.cleanup()
