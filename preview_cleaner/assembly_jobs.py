"""Page-tool worker client, sharing the proven macOS spawn/lifecycle path."""
import json
from pathlib import Path

from .jobs import CleaningJob


class AssemblyJob(CleaningJob):
    def __init__(self, options, timeout=300):
        self.outputs = []
        super().__init__(b'', '', '', False, timeout, request_options=options)

    def read_result(self):
        return json.loads((self.folder / 'report.json').read_text())

    def recover_outputs(self):
        if not hasattr(self, 'folder'):
            return
        receipt = self.folder / 'saved.jsonl'
        if receipt.exists():
            for line in receipt.read_text().splitlines():
                try:
                    path = json.loads(line)
                    if path not in self.outputs:
                        self.outputs.append(path)
                except ValueError:
                    pass  # A killed worker may leave an incomplete final receipt.
        pending = self.folder / 'publishing.json'
        if pending.exists():
            try:
                info = json.loads(pending.read_text())
                dest = Path(info['path'])
                stat = dest.stat()
                if [stat.st_dev, stat.st_ino] == info['inode'] and str(dest) not in self.outputs:
                    self.outputs.append(str(dest))
            except (ValueError, KeyError, OSError):
                pass

    def close(self, completed=False):
        if getattr(self, 'closed', False):
            return
        # Stop before recovering receipts and removing staging. The base class then
        # closes descriptors/private storage and handles partially failed startup.
        process = getattr(self, 'process', None)
        if process is not None and process.poll() is None:
            if completed:
                try:
                    process.wait(timeout=.2)
                except Exception:
                    pass
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=.2)
                except Exception:
                    process.kill()
                    process.wait()
        self.recover_outputs()
        marker = self.folder / 'staging.json'
        if marker.exists():
            try:
                path = Path(json.loads(marker.read_text()))
                if path.name == f'.{self.folder.name}.pdf.tmp':
                    path.unlink(missing_ok=True)
            except (OSError, ValueError):
                pass
        super().close(completed=True)
