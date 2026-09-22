"""Qt coordinator for immediately killable workers and parent-only publication."""
import multiprocessing
import os
from pathlib import Path
import shutil
import tempfile
import threading
from PySide6.QtCore import QObject, QTimer, Signal
from grouping.process_tasks import run_job


class Worker(QObject):
    progress = Signal(int, int, object)
    completed = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()

    def __init__(self, options, scan=False, records=None, *, target=run_job):
        super().__init__()
        self.options, self.scan, self.records = options, scan, records
        self.target = target
        self.process = None
        self.connection = None
        self.job_dir = None
        self.cancel_requested = False
        self.outcome = None
        self.preserve_job = False
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self.poll)

    def start(self):
        try:
            output = Path(self.options['output_dir']).resolve()
            output.parent.mkdir(parents=True, exist_ok=True)
            self.job_dir = Path(tempfile.mkdtemp(prefix=f'.{output.name}.job-', dir=output.parent))
            context = multiprocessing.get_context('spawn')
            self.connection, sender = context.Pipe(duplex=False)
            self.process = context.Process(target=self.target, args=(sender, self.options,
                                           self.scan, self.records, str(self.job_dir / 'result')))
            try:
                self.process.start()
            finally:
                sender.close()
            self.timer.start()
        except Exception as exc:
            self.outcome = ('failed', str(exc))
            QTimer.singleShot(0, self.finish)

    def requestInterruption(self):
        self.cancel_requested = True
        if self.process is not None and self.process.is_alive():
            # Kill the isolated process even inside ONNX or Excel code.
            self.process.kill()

    def poll(self):
        if not self.cancel_requested:
            try:
                for _ in range(64):
                    if not self.connection.poll():
                        break
                    kind, payload = self.connection.recv()
                    if kind == 'progress':
                        self.progress.emit(*payload)
                    else:
                        self.outcome = (kind, payload)
            except (EOFError, OSError):
                pass
        if not self.process.is_alive():
            # Drain buffered results before reporting completion.
            try:
                if not self.cancel_requested and self.connection.poll():
                    kind, payload = self.connection.recv()
                    if kind == 'progress':
                        self.progress.emit(*payload)
                        return
                    self.outcome = (kind, payload)
                    return
            except (EOFError, OSError):
                pass
            self.process.join(timeout=0)
            self.finish()

    def finish(self):
        self.timer.stop()
        try:
            if self.cancel_requested:
                self.cancelled.emit()
            elif self.outcome is None:
                self.failed.emit('处理进程异常退出')
            elif self.outcome[0] == 'failed':
                self.failed.emit(self.outcome[1])
            else:
                result = self.outcome[1]
                prepared = self.job_dir / 'result'
                if prepared.is_dir():
                    output = Path(self.options['output_dir']).resolve()
                    backup = self.job_dir / 'previous'
                    if output.exists():
                        os.replace(output, backup)
                    try:
                        os.replace(prepared, output)
                    except Exception:
                        if backup.exists():
                            try:
                                os.replace(backup, output)
                            except Exception:
                                self.preserve_job = True
                                raise
                        raise
                    result['output_dir'] = str(output)
                self.completed.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            if self.connection is not None:
                self.connection.close()
            if self.process is not None and self.process.pid is not None:
                self.process.close()
            if self.job_dir is not None and not self.preserve_job:
                # Only remove the exact directory allocated for this task; never
                # delay the UI for potentially large cancelled workbooks/copies.
                threading.Thread(target=shutil.rmtree, args=(self.job_dir,),
                                 kwargs={'ignore_errors': True}, daemon=True).start()
            self.finished.emit()
