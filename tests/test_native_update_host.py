"""Native installation uses the grouping host's worker and save policy."""
from PySide6.QtWidgets import QApplication
from hanzi_update import attach_updates
from ui.window import MainWindow


def test_running_worker_rejects_native_install(tmp_path, monkeypatch):
    monkeypatch.setattr('hanzi_update.native_ui.QStandardPaths.writableLocation', lambda _: str(tmp_path))
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    updater = attach_updates(window, 'group-by-character')
    updater.startup_timer.stop()
    window.show()
    try:
        window.worker = object()
        updater.prepare_close()
        assert not updater.approved and updater.ready.is_set()
        assert window.isVisible()
        assert not updater.restart_requested
        window.worker = None
        updater.prepare_close()
        assert updater.approved
        assert window.isVisible()
        updater.finish_close()
        assert not window.isVisible()
    finally:
        window.worker = None
        updater.shutdown()
        window.removeEventFilter(updater)
        window.close()
