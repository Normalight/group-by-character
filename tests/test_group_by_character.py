import json
from pathlib import Path

from PIL import Image

from group_by_character import (
    GROUP_REVIEW,
    GROUP_UNRECOGNIZED,
    classify_text,
    decode_ctc_predictions,
    iter_image_files,
    main,
    run_grouping,
    safe_output_filename,
)


def _write_image(path: Path, color="white"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (12, 16), color).save(path)


def test_iter_image_files_recurses_and_skips_hidden_and_output(tmp_path):
    _write_image(tmp_path / "root.png")
    _write_image(tmp_path / "卷一" / "page.jpg")
    _write_image(tmp_path / ".hidden" / "secret.png")
    _write_image(tmp_path / "卷一" / ".cache" / "cache.png")
    _write_image(tmp_path / "grouped" / "旧结果.png")

    files = iter_image_files(tmp_path, excluded_dir=tmp_path / "grouped")

    assert [path.relative_to(tmp_path).as_posix() for path in files] == [
        "root.png",
        "卷一/page.jpg",
    ]


def test_classify_text_sends_invalid_results_to_review():
    assert classify_text("甲", 0.95) == ("甲", "甲", "recognized")
    assert classify_text("", None) == ("", GROUP_REVIEW, "unrecognized")
    assert classify_text("甲乙", 0.95) == ("甲乙", GROUP_REVIEW, "review")
    assert classify_text("甲", 0.69) == ("甲", GROUP_REVIEW, "low_confidence")
    assert classify_text("?", 0.99) == ("?", GROUP_REVIEW, "review")


def test_decode_ctc_predictions_collapses_blanks_and_repeats():
    predictions = [
        [0.01, 0.90, 0.05, 0.04],
        [0.95, 0.02, 0.02, 0.01],
        [0.02, 0.03, 0.90, 0.05],
        [0.02, 0.03, 0.90, 0.05],
    ]

    text, score = decode_ctc_predictions(
        predictions,
        ["<blank>", "甲", "乙", "丙"],
    )

    assert text == "甲乙"
    assert score > 0.85


def test_safe_output_filename_distinguishes_same_names_in_subfolders(tmp_path):
    first = tmp_path / "a" / "page.png"
    second = tmp_path / "b" / "page.png"

    assert safe_output_filename(first, tmp_path, 0) != safe_output_filename(
        second, tmp_path, 1
    )
    assert safe_output_filename(first, tmp_path, 0).endswith(".png")


class _FakeRecognizer:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def recognize(self, image_path):
        name = Path(image_path).name
        self.calls.append(name)
        result = self.results[name]
        if isinstance(result, Exception):
            raise result
        return result


def test_run_grouping_copies_success_and_review_images_and_writes_manifest(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _write_image(input_dir / "a" / "one.png")
    _write_image(input_dir / "b" / "two.png")
    _write_image(input_dir / "three.png")
    recognizer = _FakeRecognizer(
        {
            "one.png": {"text": "甲", "score": 0.95},
            "two.png": {"text": "甲", "score": 0.91},
            "three.png": {"text": "甲乙", "score": 0.88},
        }
    )

    summary = run_grouping(input_dir, output_dir, recognizer)

    assert summary["record_count"] == 3
    assert summary["group_count"] == 2
    assert len(list((output_dir / "按字" / "甲").glob("*.png"))) == 2
    assert len(list((output_dir / "按字" / GROUP_REVIEW).glob("*.png"))) == 1
    manifest = json.loads(
        (output_dir / "归并清单.json").read_text(encoding="utf-8")
    )
    assert manifest["record_count"] == 3
    assert {
        record["source_relative_path"] for record in manifest["records"]
    } == {"a/one.png", "b/two.png", "three.png"}
    assert (output_dir / "字形归并.xlsx").is_file()


def test_run_grouping_isolates_one_recognition_failure(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _write_image(input_dir / "bad.png")
    _write_image(input_dir / "good.png")
    recognizer = _FakeRecognizer(
        {
            "bad.png": RuntimeError("broken image"),
            "good.png": {"text": "善", "score": 0.9},
        }
    )

    summary = run_grouping(input_dir, output_dir, recognizer)

    assert summary["record_count"] == 2
    assert summary["unrecognized_count"] == 0
    assert summary["review_count"] == 1
    assert len(list((output_dir / "按字" / "善").glob("*.png"))) == 1
    bad = next(
        record
        for record in json.loads(
            (output_dir / "归并清单.json").read_text(encoding="utf-8")
        )["records"]
        if record["source_relative_path"] == "bad.png"
    )
    assert "broken image" in bad["recognition_error"]


def test_run_grouping_keeps_corrupt_image_failure_isolated_and_writes_output(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    (input_dir / "bad.png").write_bytes(b"not an image")
    _write_image(input_dir / "good.png")
    recognizer = _FakeRecognizer(
        {
            "bad.png": RuntimeError("cannot decode"),
            "good.png": {"text": "善", "score": 0.9},
        }
    )

    summary = run_grouping(input_dir, output_dir, recognizer)

    assert summary["record_count"] == 2
    assert output_dir.is_dir()
    assert (output_dir / "字形归并.xlsx").is_file()
    assert (output_dir / "归并清单.json").is_file()


def test_main_empty_input_does_not_load_missing_model(tmp_path, capsys):
    input_dir = tmp_path / "empty"
    input_dir.mkdir()

    exit_code = main(
        [
            "--input",
            str(input_dir),
            "--output",
            str(tmp_path / "output"),
            "--model",
            str(tmp_path / "missing.onnx"),
        ]
    )

    assert exit_code == 0
    assert "0 张" in capsys.readouterr().out


def test_run_grouping_rejects_output_that_contains_input(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_image(input_dir / "one.png")

    try:
        run_grouping(input_dir, tmp_path, _FakeRecognizer({"one.png": "甲"}))
    except ValueError as exc:
        assert "输出目录" in str(exc)
    else:
        raise AssertionError("输出目录祖先必须被拒绝")


def test_dry_run_scans_without_loading_model_or_writing_output(tmp_path, capsys):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _write_image(input_dir / "one.png")

    exit_code = main(
        [
            "--input",
            str(input_dir),
            "--output",
            str(output_dir),
            "--dry-run",
        ]
    )

    assert exit_code == 0
    assert "1" in capsys.readouterr().out
    assert not output_dir.exists()


def test_upstream_auto_excludes_overview_and_supports_pdf_layout(tmp_path):
    from group_by_character import iter_image_files
    for name in ['碑/page_001/来源-碑_p001_crop_0.png', '碑/page_001/碑_p001_overview.png', '旧版/char_12.jpg']:
        _write_image(tmp_path / name)
    assert len(iter_image_files(tmp_path)) == 2
    assert len(iter_image_files(tmp_path, input_format='crops')) == 2
    assert len(iter_image_files(tmp_path, input_format='images')) == 3


def test_cancel_keeps_previous_output(tmp_path):
    import pytest
    from group_by_character import GroupingCancelled
    root, output = tmp_path / 'input', tmp_path / 'output'
    _write_image(root / 'one.png')
    output.mkdir()
    (output / 'sentinel').write_text('old')
    progressed = []
    with pytest.raises(GroupingCancelled):
        run_grouping(root, output, _FakeRecognizer({'one.png': ('甲', .99)}),
                     progress=lambda *args: progressed.append(args), cancelled=lambda: bool(progressed))
    assert (output / 'sentinel').read_text() == 'old'
    assert not list(tmp_path.glob('.output.building-*'))


def test_manual_export_without_recognizer(tmp_path):
    from group_by_character import GroupRecord
    root, output = tmp_path / 'input', tmp_path / 'output'
    _write_image(root / 'one.png')
    record = GroupRecord(str(root / 'one.png'), 'one.png', '乙', '乙', 'manual', .2)
    run_grouping(root, output, None, records_override=[record])
    saved = json.loads((output / '归并清单.json').read_text(encoding='utf-8'))['records'][0]
    assert saved['group_label'] == '乙'
    assert saved['status'] == 'manual'
    assert saved['recognition_score'] == .2
    assert (output / saved['output_relative_path']).exists()
