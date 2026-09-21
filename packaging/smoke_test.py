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
    from hanzi_auth import require_login, protect_window
    assert callable(require_login) and callable(protect_window)
    from PIL import Image
    app = QApplication.instance() or QApplication([])
    from hanzi_auth.desktop import LoginDialog
    from hanzi_auth.updates import build_info
    from hanzi_auth.update_ui import UpdateController
    from types import SimpleNamespace
    product = 'group-by-character'
    assert build_info(product)["product"] == product
    from hanzi_auth.single_instance import SingleInstance
    with tempfile.TemporaryDirectory(prefix='single-instance-smoke-') as lock_dir:
        owner = SingleInstance(product, lock_dir)
        duplicate = SingleInstance(product, lock_dir)
        assert owner.acquire()
        assert not duplicate.acquire()
        owner.close()
        assert duplicate.acquire()
        duplicate.close()
    from hanzi_auth.credentials import backend
    import uuid
    vault = backend()
    service = 'HanziTools.SmokeTest.' + uuid.uuid4().hex
    try:
        vault.set_password(service, 'smoke-test', 'temporary-smoke-value')
        assert vault.get_password(service, 'smoke-test') == 'temporary-smoke-value'
    finally:
        vault.delete_password(service, 'smoke-test')
    assert vault.get_password(service, 'smoke-test') is None
    login = LoginDialog(product)
    assert login.server_url.startswith(("https://", "http://"))
    login.reject()
    window = MainWindow()
    updates = UpdateController(window, SimpleNamespace(
        locked=True, session=SimpleNamespace(product=product)))
    updates.startup_timer.stop()
    assert updates.action.text() == "检查更新…"
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
                      'checks':['login and update UI','Qt window','frozen spawn','ONNX inference','JSON and Excel export']}, ensure_ascii=False))
