"""Smoke tests executed from the actual frozen runtime (no source checkout needed)."""
import json
import platform
import tempfile
from pathlib import Path


def smoke_test():
    import sys
    assert getattr(sys, "frozen", False), "Run smoke tests from the packaged application"
    from PySide6.QtWidgets import QApplication
    from app import MainWindow
    from PIL import Image
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    window.hide()
    import multiprocessing
    import config
    from process_tasks import run_job
    with tempfile.TemporaryDirectory(prefix='归并打包验证-') as temp:
        source = Path(temp) / '输入'
        source.mkdir()
        Image.new('RGB', (48, 48), 'white').save(source / 'char_001.png')
        output = Path(temp) / '输出'
        options = dict(input_dir=str(source), output_dir=str(output),
                       model=str(config.model_path()), yaml=str(config.dictionary_path()),
                       input_format='auto', confidence_threshold=0.5)
        context = multiprocessing.get_context('spawn')
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=run_job,
                                  args=(sender, options, False, None, str(output)))
        process.start()
        sender.close()
        try:
            result = None
            import time
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                app.processEvents()
                if receiver.poll(0.05):
                    kind, payload = receiver.recv()
                    if kind == 'failed':
                        raise RuntimeError(payload)
                    if kind == 'completed':
                        result = payload
                        break
                if not process.is_alive() and not receiver.poll():
                    break
            process.join(timeout=10)
            assert result is not None and process.exitcode == 0, 'Frozen worker did not complete'
            assert result['record_count'] == 1
            assert (output / '归并清单.json').is_file()
            assert (output / '字形归并.xlsx').is_file()
        finally:
            if process.is_alive():
                process.kill()
                process.join()
            receiver.close()
            process.close()
    window.close()
    print(json.dumps({'smoke_test':'passed', 'arch':platform.machine(),
                      'checks':['Qt window','frozen spawn','ONNX inference','JSON and Excel export']}, ensure_ascii=False))
