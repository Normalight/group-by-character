import json
from dataclasses import replace
from unittest.mock import Mock
import pytest
from PIL import Image
from grouping import service
from grouping.save_cache import unchanged_export


def setup_output(tmp_path):
    root = tmp_path / 'input'; root.mkdir()
    image = root / 'one.png'; Image.new('RGB',(30,40),'white').save(image)
    records = [service.GroupRecord(str(image),'one.png','甲','甲','manual',.9)]
    output = tmp_path / 'output'
    service.run_grouping(root, output, None, records_override=records)
    records = [service.GroupRecord(**r) for r in json.loads((output/'归并清单.json').read_text())['records']]
    return root, output, records


def test_review_reuses_images_and_thumbnails(tmp_path, monkeypatch):
    root, output, records = setup_output(tmp_path)
    assert unchanged_export(output, records)
    thumbnail = Mock(wraps=service._thumbnail)
    monkeypatch.setattr(service, '_thumbnail', thumbnail)
    copy = Mock(wraps=service.shutil.copy2)
    monkeypatch.setattr(service.shutil, 'copy2', copy)
    records[0] = replace(records[0], recognized_text='乙', group_label='乙')
    assert not unchanged_export(output, records)
    service.run_grouping(root, output, None, records_override=records)
    assert thumbnail.call_count == copy.call_count == 0
    saved = [service.GroupRecord(**r) for r in json.loads((output/'归并清单.json').read_text())['records']]
    assert saved[0].group_label == '乙'
    assert unchanged_export(output, saved)
    Image.new('RGB',(30,40),'black').save(root/'one.png')
    assert not unchanged_export(output, saved)
    service.run_grouping(root, output, None, records_override=saved)
    assert thumbnail.call_count == 1


def test_missing_assets_and_workbook_require_repair(tmp_path):
    root, output, records = setup_output(tmp_path)
    (output/'字形归并.xlsx').write_bytes(b'changed')
    assert not unchanged_export(output, records)
    service.run_grouping(root,output,None,records_override=records)
    next((output/'.thumbnails').iterdir()).unlink()
    assert not unchanged_export(output, records)


def test_failed_rebuild_keeps_previous_results(tmp_path, monkeypatch):
    root, output, records = setup_output(tmp_path)
    before = (output/'字形归并.xlsx').read_bytes()
    monkeypatch.setattr(service, 'build_workbook', Mock(side_effect=OSError('disk full')))
    with pytest.raises(OSError):
        service.run_grouping(root,output,None,records_override=[replace(records[0],group_label='乙')])
    assert (output/'字形归并.xlsx').read_bytes() == before
    assert (output/records[0].output_relative_path).is_file()
