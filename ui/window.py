"""Qt 字形归并与人工复核界面。运行：conda run -n chardet python app.py"""

from pathlib import Path
import sys
from dataclasses import replace
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap, QDesktopServices, QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QFileDialog, QDoubleSpinBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QLabel, QSplitter, QMessageBox, QAbstractItemView,
)
from grouping.service import (
    PPOcrV6CharacterRecognizer, run_grouping, iter_image_files, classify_text,
    GroupingCancelled, GROUP_REVIEW,
)

import config

STATUS_LABELS = {
    'recognized': '已识别',
    'unrecognized': '未识别',
    'review': '待复核',
    'missing_confidence': '缺少置信度',
    'low_confidence': '低置信度',
    'recognition_error': '识别失败',
    'manual': '人工已确认',
}


from ui.task_worker import Worker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('字形归并 · 识别与复核')
        self.resize(1180, 800)
        self.worker = None
        self._update_save_pending = False
        self._update_save_succeeded = False
        self.records = []
        self.saved_options = None
        self.dirty = False
        self.pending_records = []
        self.deleted_batches = []
        body = QWidget()
        self.setCentralWidget(body)
        layout = QVBoxLayout(body)
        title = QLabel('字形归并')
        title.setStyleSheet('font-size:24px;font-weight:600;padding:8px')
        layout.addWidget(title)
        self.settings = QWidget()
        form = QFormLayout(self.settings)
        self.input = self.path_field(form, '输入目录', str(Path.home()), True)
        self.output = self.path_field(form, '输出目录', str(config.application_dir() / 'grouped-output'), True)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0, 1)
        self.threshold.setSingleStep(.05)
        self.threshold.setValue(.70)
        form.addRow('置信度阈值', self.threshold)
        layout.addWidget(self.settings)
        buttons = QHBoxLayout()
        self.scan = QPushButton('扫描数量')
        self.start = QPushButton('开始识别归档')
        self.cancel = QPushButton('取消')
        self.cancel.setEnabled(False)
        self.export = QPushButton('保存复核结果')
        self.export.setEnabled(False)
        self.open_output = QPushButton('打开输出目录')
        self.check_updates_button = QPushButton('检查更新')
        for button in (self.scan, self.start, self.cancel, self.export, self.open_output, self.check_updates_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.scan.clicked.connect(lambda: self.launch(scan=True))
        self.start.clicked.connect(lambda: self.launch())
        self.cancel.clicked.connect(self.stop)
        self.export.clicked.connect(lambda: self.launch(export=True))
        self.open_output.clicked.connect(self.open_folder)
        self.bar = QProgressBar()
        layout.addWidget(self.bar)
        self.status = QLabel('就绪')
        layout.addWidget(self.status)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('筛选字符、待复核或来源路径…')
        self.filter.textChanged.connect(self.filter_rows)
        layout.addWidget(self.filter)
        split = QSplitter()
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(['字符', '分组', '置信度', '状态', '来源'])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemSelectionChanged.connect(self.preview)
        split.addWidget(self.table)
        review = QWidget()
        review_layout = QVBoxLayout(review)
        self.image = QLabel('选择一行预览图片')
        self.image.setAlignment(Qt.AlignCenter)
        self.image.setMinimumSize(240, 220)
        review_layout.addWidget(self.image)
        self.correction = QLineEdit()
        self.correction.setPlaceholderText('输入正确的单个字符')
        review_layout.addWidget(self.correction)
        self.apply = QPushButton('应用改字')
        self.apply.clicked.connect(self.correct)
        review_layout.addWidget(self.apply)
        self.delete = QPushButton('删除选中项 (Delete)')
        self.delete.clicked.connect(self.delete_selected)
        review_layout.addWidget(self.delete)
        self.undo_delete = QPushButton('撤销删除')
        self.undo_delete.setEnabled(False)
        self.undo_delete.clicked.connect(self.restore_deleted)
        review_layout.addWidget(self.undo_delete)
        self.delete_shortcut = QShortcut(QKeySequence('Delete'), self.table)
        self.delete_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.delete_shortcut.activated.connect(self.delete_selected)
        split.addWidget(review)
        split.setStretchFactor(0, 3)
        layout.addWidget(split, 1)

    def path_field(self, form, label, value, directory):
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(value)
        button = QPushButton('浏览…')
        def choose():
            path = (QFileDialog.getExistingDirectory(self, label, edit.text()) if directory else
                    QFileDialog.getOpenFileName(self, label, edit.text())[0])
            if path:
                edit.setText(path)
        button.clicked.connect(choose)
        line.addWidget(edit)
        line.addWidget(button)
        form.addRow(label, row)
        return edit

    def options(self):
        if not self.input.text().strip() or not self.output.text().strip():
            raise ValueError('请选择输入和输出目录')
        root = Path(self.input.text()).resolve()
        output = Path(self.output.text()).resolve()
        if not root.is_dir():
            raise ValueError('输入目录不存在')
        if root == output or output in root.parents:
            raise ValueError('输出目录不能与输入目录相同或包含输入目录')
        return dict(input_dir=str(root), output_dir=str(output), model=str(config.model_path()),
                    yaml=str(config.dictionary_path()), input_format=config.DEFAULT_INPUT_FORMAT,
                    confidence_threshold=self.threshold.value())

    def launch(self, scan=False, export=False):
        from hanzi_auth import is_locked
        if is_locked(self) and not export:
            return
        if export and self.saved_options is None:
            self.status.setText('当前没有可保存的复核结果。')
            return
        if self.worker is not None:
            return
        try:
            opts = self.saved_options.copy() if export else self.options()
            if export and not self.dirty:
                from grouping.save_cache import unchanged_export
                if unchanged_export(opts['output_dir'], self.records):
                    self.status.setText('结果没有变化，已保留本地保存。')
                    return
            if not scan:
                output = Path(opts['output_dir'])
                if output.exists() and any(output.iterdir()):
                    if not (output / '归并清单.json').is_file() or not (output / '按字').is_dir():
                        raise ValueError('输出目录非空且不是本工具的归并结果，请选择新的输出目录。')
                    if QMessageBox.question(self, '替换归并结果', '将重新生成该输出目录中的全部内容，是否继续？') != QMessageBox.Yes:
                        return
                if self.dirty and not export:
                    if QMessageBox.question(self, '未保存的复核', '开始新任务将丢弃未保存的复核修改，是否继续？') != QMessageBox.Yes:
                        return
            self.pending_records = []
            self.active_options = opts
            self.worker = Worker(opts, scan, [replace(r) for r in self.records] if export else None)
            self.worker.progress.connect(self.on_progress)
            self.worker.completed.connect(self.on_completed)
            self.worker.failed.connect(self.on_error)
            self.worker.cancelled.connect(lambda: self.status.setText('已取消，原有输出保留。'))
            self.worker.finished.connect(self.on_finished)
            self.set_busy(True)
            self.bar.setRange(0, 0)
            self.status.setText('正在扫描 / 加载模型…')
            self.worker.start()
        except Exception as exc:
            self.on_error(str(exc))

    def set_busy(self, busy):
        for widget in (self.settings, self.scan, self.start, self.apply, self.delete):
            widget.setEnabled(not busy)
        self.export.setEnabled(not busy and self.saved_options is not None)
        self.undo_delete.setEnabled(not busy and bool(self.deleted_batches))
        self.delete_shortcut.setEnabled(not busy)
        self.cancel.setEnabled(busy)

    def stop(self):
        if self.worker:
            self.worker.requestInterruption()
            self.status.setText('已取消')
            self.cancel.setEnabled(False)
            self.pending_records = []
            self.bar.setRange(0, 1)
            self.bar.setValue(0)

    def on_progress(self, done, total, record):
        self.pending_records.append(record)
        self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.status.setText(f'{done} / {total} · {record.source_relative_path}' if done < total else '识别完成，正在生成 Excel 与清单…')

    def on_completed(self, result):
        if 'scan_count' in result:
            self.status.setText(f"发现 {result['scan_count']} 张待处理图片")
        else:
            self.records = self.pending_records
            self.saved_options = self.active_options.copy()
            self.dirty = False
            if self._update_save_pending:
                self._update_save_succeeded = True
            self.deleted_batches.clear()
            self.populate()
            self.status.setText(f"完成：{result['record_count']} 张，{result['group_count']} 个分组，{result['review_count']} 张待复核")

    def on_finished(self):
        self.worker.deleteLater()
        self.worker = None
        self.set_busy(False)
        if self.bar.maximum() == 0:
            self.bar.setRange(0, 1)
            self.bar.setValue(1)
        if self._update_save_pending:
            self._update_save_pending = False
            if self._update_save_succeeded and not self.dirty:
                self.close()
            else:
                self._update_controller.restart_requested = False

    def on_error(self, message):
        self.status.setText('失败：' + message)
        QMessageBox.warning(self, '处理失败', message)

    def populate(self):
        self.table.clearSelection()
        self.image.setText("选择一行预览图片")
        self.correction.clear()
        self.table.setRowCount(len(self.records))
        for i, record in enumerate(self.records):
            values = [record.recognized_text, record.group_label,
                      '' if record.recognition_score is None else f'{record.recognition_score:.3f}',
                      STATUS_LABELS.get(record.status, '未知状态'), record.source_relative_path]
            for j, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(record.recognition_error or record.source_path)
                self.table.setItem(i, j, item)
        self.filter_rows()

    def filter_rows(self):
        query = self.filter.text().strip().casefold()
        for i, record in enumerate(self.records):
            self.table.setRowHidden(i, query not in f'{record.recognized_text} {record.group_label} {record.source_relative_path}'.casefold())

    def preview(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.records):
            record = self.records[row]
            pix = QPixmap(record.source_path)
            self.image.setPixmap(pix.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            if pix.isNull():
                self.image.setText('图片无法读取')
            self.correction.setText(record.recognized_text)

    def correct(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self.records):
            return
        text, group, status = classify_text(self.correction.text(), 1.0)
        if group == GROUP_REVIEW:
            QMessageBox.warning(self, '无效字符', '请输入一个可用于归档的字符。')
            return
        record = self.records[row]
        record.recognized_text, record.group_label, record.status = text, group, 'manual'
        self.dirty = True
        self.populate()
        self.status.setText('已改字，点击“保存复核结果”写入输出。')

    def delete_selected(self):
        if self.worker is not None:
            return
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()
                       if not self.table.isRowHidden(index.row())})
        if not rows:
            return
        self.deleted_batches.append([(row, self.records[row]) for row in rows])
        for row in reversed(rows):
            del self.records[row]
        self.dirty = True
        self.populate()
        self.set_busy(False)
        self.status.setText(f'已删除 {len(rows)} 项，可撤销；点击“保存复核结果”写入输出。')

    def restore_deleted(self):
        if self.worker is not None or not self.deleted_batches:
            return
        for row, record in self.deleted_batches.pop():
            self.records.insert(row, record)
        self.dirty = True
        self.populate()
        self.set_busy(False)
        self.status.setText('已撤销上次删除，点击“保存复核结果”写入输出。')

    def open_folder(self):
        path = self.saved_options['output_dir'] if self.saved_options else self.output.text()
        if Path(path).is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def closeEvent(self, event):
        updater = getattr(self, '_update_controller', None)
        if updater is not None and updater.restart_requested:
            if self._update_save_pending:
                event.ignore()
                return
            if self.worker:
                updater.restart_requested = False
                self.status.setText('请等待当前任务完成后，再保存并重启更新。')
                event.ignore()
                return
            if self.dirty:
                event.ignore()
                self._update_save_pending = True
                self._update_save_succeeded = False
                self.launch(export=True)
                if self.worker is None:
                    self._update_save_pending = False
                    updater.restart_requested = False
                return
        if self.worker:
            self.stop()
            event.ignore()
            return
        if self.dirty and QMessageBox.question(self, '未保存的复核', '复核修改尚未保存，是否退出？') != QMessageBox.Yes:
            event.ignore()
            return
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    from hanzi_auth import start_session, protect_window
    from hanzi_update import attach_updates
    session = start_session(app, 'group-by-character')
    if session is None:
        return 0
    window = MainWindow()
    guard = protect_window(window, session, lambda: window.launch(export=True), window.stop)
    attach_updates(window, session.product, button=window.check_updates_button,
                   is_locked=lambda: guard.locked, precheck=guard.check_native_update)
    window.show()
    return app.exec()


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
