"""Smoke tests executed from the actual frozen runtime (no source checkout needed)."""
import json
import os
import platform
import tempfile
from pathlib import Path


def smoke_test():
    import sys
    assert getattr(sys, "frozen", False), "Run smoke tests from the packaged application"
    from PySide6.QtWidgets import QApplication
    from ui.window import MainWindow
    from hanzi_auth import require_login, protect_window
    assert callable(require_login) and callable(protect_window)
    from PIL import Image
    app = QApplication.instance() or QApplication([])
    from hanzi_auth.desktop import LoginDialog
    from hanzi_auth.updates import build_info
    from hanzi_auth.update_ui import UpdateController
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
    from hanzi_auth.credentials import CredentialStore
    with tempfile.TemporaryDirectory(prefix='credentials-smoke-') as credential_dir:
        vault = CredentialStore('https://smoke.invalid', credential_dir)
        vault.set('smoke-test', 'temporary-smoke-value')
        assert vault.get('smoke-test') == 'temporary-smoke-value'
        vault.delete('smoke-test')
        assert vault.get('smoke-test') == ''
    login = LoginDialog(product)
    assert login.server_url.startswith(("https://", "http://"))
    login.reject()
    window = MainWindow()
    updates = UpdateController(window, product, is_locked=lambda: True)
    updates.startup_timer.stop()
    assert updates.action.text() == "检查更新…"
    # Validate the native adapter and shipped SDK after final bundle assembly.
    from hanzi_update import attach_updates
    native = attach_updates(window, product, is_locked=lambda: True)
    native.startup_timer.stop()
    from hanzi_update.backends.base import UpdateConfig
    from hanzi_update.backends import create_updater
    config_path = Path(sys._MEIPASS) / 'native_update.json'
    if config_path.is_file():
        config = UpdateConfig(**json.loads(config_path.read_text(encoding='utf-8')))
        location = Path(sys.executable).resolve().parent
        if sys.platform == 'darwin':
            bundles = [p for p in Path(sys.executable).resolve().parents if p.suffix == '.app']
            location = bundles[-1]
            assembled = (location / 'Contents/Frameworks/SparkleBridge.dylib').is_file()
        else:
            assembled = (location / 'WinSparkle.dll').is_file()
        if assembled:
            backend = create_updater(config, location, prepare=lambda: 0,
                                     shutdown=lambda: None, event=lambda _: None)
            if sys.platform == 'win32':
                import ctypes
                assert backend.bind('set_eddsa_public_key', [ctypes.c_char_p], ctypes.c_int)(config.public_key.encode()) == 1
    native.shutdown()
    window.show()
    app.processEvents()
    window.hide()
    from PySide6.QtGui import QImageReader
    from PySide6.QtWidgets import QLineEdit
    text_input = QLineEdit()
    text_input.setText('中文输入测试')
    assert text_input.text() == '中文输入测试'
    with tempfile.TemporaryDirectory(prefix='image-codec-smoke-') as temp:
        for extension in ('png', 'jpg', 'bmp', 'tiff', 'webp'):
            image_path = Path(temp) / ('图片.' + extension)
            Image.new('RGB', (32, 24), 'white').save(image_path)
            decoded = QImageReader(str(image_path)).read()
            assert not decoded.isNull(), f'Qt cannot read {extension}'
            assert (decoded.width(), decoded.height()) == (32, 24)
    import multiprocessing
    import config
    from grouping.process_tasks import run_job
    with tempfile.TemporaryDirectory(prefix='归并打包验证-') as temp:
        source = Path(temp) / '输入'
        source.mkdir()
        fixture = os.environ.get('HANZI_SMOKE_IMAGE')
        image = Image.open(fixture).convert('RGB') if fixture else Image.new('RGB', (48, 48), 'white')
        image.save(source / 'char_001.png')
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
                      'checks':['login and update UI','Qt window','image codecs','Unicode widgets','frozen spawn','ONNX inference','JSON and Excel export']}, ensure_ascii=False))
