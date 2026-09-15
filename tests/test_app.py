import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app import MainWindow
from group_by_character import GroupRecord
from PIL import Image


def test_gui_scan_preview_and_manual_correction(tmp_path):
    app = QApplication.instance() or QApplication([])
    image = tmp_path / 'page_crop_0.png'
    Image.new('RGB', (24, 32), 'white').save(image)
    window = MainWindow()
    window.input.setText(str(tmp_path))
    window.output.setText(str(tmp_path / 'grouped'))
    window.show()
    window.scan.click()
    for _ in range(500):
        QTest.qWait(10)
        if window.worker is None:
            break
    assert window.worker is None
    assert '1 张' in window.status.text()
    window.records = [GroupRecord(str(image), image.name, '甲', '待复核', 'low_confidence', .2)]
    window.populate()
    window.table.selectRow(0)
    assert not window.image.pixmap().isNull()
    window.correction.setText('乙')
    window.apply.click()
    assert window.records[0].group_label == '乙'
    assert window.records[0].status == 'manual'
    assert window.table.item(0, 3).text() == '人工已确认'
    window.filter.setText('丙')
    assert window.table.isRowHidden(0)
    window.dirty = False
    window.close()


def test_delete_undo_and_save_empty_result(tmp_path, monkeypatch):
    import json
    from PySide6.QtWidgets import QMessageBox
    from group_by_character import run_grouping
    app = QApplication.instance() or QApplication([])
    root, output = tmp_path / 'input', tmp_path / 'output'
    root.mkdir()
    records = []
    for index, char in enumerate('甲乙'):
        image = root / f'crop_{index}.png'
        Image.new('RGB', (24, 32), 'white').save(image)
        records.append(GroupRecord(str(image), image.name, char, char, 'recognized', .9))
    run_grouping(root, output, None, records_override=records)
    window = MainWindow()
    window.input.setText(str(root))
    window.output.setText(str(output))
    window.saved_options = window.options()
    window.records = records.copy()
    window.populate()
    window.show()
    window.table.selectAll()
    window.delete.click()
    assert window.records == []
    assert window.export.isEnabled()
    assert window.image.text() == '选择一行预览图片'
    window.undo_delete.click()
    assert [r.recognized_text for r in window.records] == ['甲', '乙']
    window.filter.setText('甲')
    window.table.selectAll()
    window.delete.click()
    assert [r.recognized_text for r in window.records] == ['乙']
    window.filter.clear()
    window.table.selectAll()
    window.delete.click()
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.Yes)
    window.export.click()
    for _ in range(500):
        QTest.qWait(10)
        if window.worker is None:
            break
    assert window.worker is None
    assert not window.dirty
    assert not window.deleted_batches
    manifest = json.loads((output / '归并清单.json').read_text(encoding='utf-8'))
    assert manifest['records'] == []
    assert not list((output / '按字').rglob('*.png'))
    assert (output / '字形归并.xlsx').is_file()
    assert len(list(root.glob('*.png'))) == 2
    window.close()
