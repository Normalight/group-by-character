import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from task_worker import Worker


def blocked_task(connection, options, scan, records, result_dir):
    Path(result_dir).mkdir()
    (Path(result_dir) / 'partial').write_text('incomplete')
    connection.send(('progress', (1, 2, None)))
    time.sleep(60)  # models and workbook generation need not cooperate
    connection.send(('completed', {}))


def test_cancel_kills_blocked_process_and_keeps_saved_output(tmp_path):
    app = QApplication.instance() or QApplication([])
    output = tmp_path / 'output'
    output.mkdir()
    marker = output / 'saved'
    marker.write_text('original')
    worker = Worker({'output_dir': str(output)}, target=blocked_task)
    ready, finished, cancelled, completed = [], [], [], []
    worker.progress.connect(lambda *args: ready.append(True))
    worker.finished.connect(lambda: finished.append(True))
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.completed.connect(completed.append)
    worker.start()
    for _ in range(1500):
        QTest.qWait(10)
        if ready:
            break
    assert ready
    started = time.monotonic()
    worker.requestInterruption()
    for _ in range(100):
        QTest.qWait(10)
        if finished:
            break
    assert finished and cancelled and not completed
    assert time.monotonic() - started < 1.0
    assert marker.read_text() == 'original'
    assert not (output / 'partial').exists()
