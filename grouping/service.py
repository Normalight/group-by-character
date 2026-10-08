"""递归扫描图片并按识别字符归档的独立命令行工具。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import unicodedata
from typing import Iterable, Optional

from grouping.recognition import PPOcrV6CharacterRecognizer, decode_ctc_predictions
from PIL import Image

logger = logging.getLogger(__name__)

GROUP_REVIEW = "待复核"
GROUP_UNRECOGNIZED = "未识别"
DEFAULT_CONFIDENCE_THRESHOLD = 0.70
IMAGE_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
)
INVALID_PATH_CHARS = frozenset('/\\:*?"<>|')


@dataclass
class GroupRecord:
    source_path: str
    source_relative_path: str
    recognized_text: str
    group_label: str
    status: str
    recognition_score: Optional[float] = None
    recognition_error: str = ""
    output_relative_path: str = ""


def _resolved(path: os.PathLike | str) -> Path:
    return Path(path).expanduser().resolve()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def iter_image_files(
    input_dir: os.PathLike | str,
    *,
    excluded_dir: os.PathLike | str | None = None,
    input_format: str = "auto",
) -> list[Path]:
    """递归发现图片，忽略隐藏路径和指定输出子树。"""

    root = _resolved(input_dir)
    if not root.is_dir():
        raise NotADirectoryError(f"输入目录不存在或不是目录：{root}")
    excluded = _resolved(excluded_dir) if excluded_dir is not None else None
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        relative_parts = path.relative_to(root).parts
        if any(part.startswith(".") for part in relative_parts):
            continue
        if excluded is not None and _is_relative_to(path, excluded):
            continue
        files.append(path)
    if input_format not in {"auto", "crops", "images"}:
        raise ValueError("未知输入格式")
    crops = [p for p in files if re.search(r"(?:_crop_|^char_)\d+$", p.stem)]
    if input_format == "crops" or (input_format == "auto" and crops):
        files = crops
    return sorted(
        files,
        key=lambda path: path.relative_to(root).as_posix(),
    )


def _finite_score(value) -> Optional[float]:
    if value is None:
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if math.isfinite(score) else None


def classify_text(
    text: object,
    confidence: Optional[float],
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> tuple[str, str, str]:
    """返回 ``(规范文字, 展示分组, 状态)``。"""

    normalized = unicodedata.normalize(
        "NFC",
        "".join(str(text or "").split()),
    )
    score = _finite_score(confidence)
    if not normalized:
        return "", GROUP_REVIEW, "unrecognized"
    if len(normalized) != 1:
        return normalized, GROUP_REVIEW, "review"
    char = normalized[0]
    if (
        char in {"?", "."}
        or char in INVALID_PATH_CHARS
        or unicodedata.category(char).startswith("C")
    ):
        return normalized, GROUP_REVIEW, "review"
    if score is None:
        return normalized, GROUP_REVIEW, "missing_confidence"
    if score < float(confidence_threshold):
        return normalized, GROUP_REVIEW, "low_confidence"
    return normalized, char, "recognized"


def _safe_component(value: object, fallback: str) -> str:
    cleaned = "".join(
        "_" if char in INVALID_PATH_CHARS or ord(char) < 32 else char
        for char in str(value or "")
    ).strip().strip(".")
    return cleaned or fallback


def safe_output_filename(
    source_path: os.PathLike | str,
    input_dir: os.PathLike | str,
    sequence_index: int,
) -> str:
    """生成包含相对路径和哈希的稳定文件名，避免子目录同名覆盖。"""

    source = _resolved(source_path)
    root = _resolved(input_dir)
    relative = source.relative_to(root).as_posix()
    stem = _safe_component(Path(relative).with_suffix("").as_posix(), "source")
    stem = re.sub(r"[/\\\s]+", "_", stem)
    digest = hashlib.sha1(relative.encode("utf-8")).hexdigest()[:10]
    suffix = source.suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        suffix = ".png"
    return f"{stem}_{int(sequence_index) + 1:06d}_{digest}{suffix}"


def _normalize_recognition(result) -> tuple[str, Optional[float]]:
    if isinstance(result, dict):
        text = result.get("text")
        if text is None:
            text = result.get("line_pred", result.get("raw", ""))
        score = result.get("score")
        if score is None:
            char_list = result.get("char_list")
            if isinstance(char_list, list) and len(char_list) == 1:
                score = char_list[0].get("score")
        return "" if text is None else str(text), _finite_score(score)
    if isinstance(result, (tuple, list)) and result:
        return str(result[0]), _finite_score(result[1] if len(result) > 1 else None)
    return str(result or ""), None


def _group_component(group_label: str) -> str:
    return _safe_component(group_label, GROUP_REVIEW)


def _write_manifest(staging_dir: Path, records: Iterable[GroupRecord]) -> None:
    records = list(records)
    counts = {}
    for record in records:
        counts[record.group_label] = counts.get(record.group_label, 0) + 1
    payload = {
        "version": 1,
        "record_count": len(records),
        "groups": dict(sorted(counts.items())),
        "records": [asdict(record) for record in records],
    }
    (staging_dir / "归并清单.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _replace_output(staging_dir: Path, output_dir: Path) -> None:
    backup_dir = output_dir.parent / f".{output_dir.name}.backup"
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    if output_dir.exists():
        os.replace(output_dir, backup_dir)
    try:
        os.replace(staging_dir, output_dir)
    except Exception:
        if backup_dir.exists() and not output_dir.exists():
            os.replace(backup_dir, output_dir)
        raise
    if backup_dir.exists():
        shutil.rmtree(backup_dir)


class GroupingCancelled(Exception):
    """用户取消，保留此前输出。"""


def run_grouping(
    input_dir: os.PathLike | str,
    output_dir: os.PathLike | str,
    recognizer,
    *,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    input_format: str = "auto",
    progress=None,
    cancelled=None,
    records_override=None,
    source_files=None,
    reuse_dir=None,
) -> dict:
    """递归识别并原子构建按字目录与 JSON 清单。"""

    started = time.perf_counter()
    root = _resolved(input_dir)
    output = _resolved(output_dir)
    if output == root or _is_relative_to(root, output):
        raise ValueError("输出目录不能与输入目录相同或包含输入目录")
    if not 0 <= confidence_threshold <= 1:
        raise ValueError("置信度必须在 0 到 1 之间")
    from grouping.save_cache import file_stamp, read_cache, write_cache, clone_saved
    previous_root = _resolved(reuse_dir) if reuse_dir else output
    previous = read_cache(previous_root / '.save-cache.json')
    previous_entries = previous.get('entries', {})
    if not isinstance(previous_entries, dict):
        previous_entries = {}
    overrides = {r.source_path: r for r in records_override} if records_override is not None else None
    files = ([Path(r.source_path) for r in records_override] if records_override is not None
             else list(source_files) if source_files is not None
             else iter_image_files(root, excluded_dir=output, input_format=input_format))
    if not files and records_override is None:
        return {
            "output_dir": str(output),
            "record_count": 0,
            "group_count": 0,
            "review_count": 0,
            "unrecognized_count": 0,
        }

    output.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}.building-",
            dir=str(output.parent),
        )
    )
    records: list[GroupRecord] = []
    cache_entries = {}
    try:
        grouped_root = staging_dir / "按字"
        grouped_root.mkdir()
        for index, source_path in enumerate(files):
            if cancelled and cancelled():
                raise GroupingCancelled()
            relative = source_path.relative_to(root).as_posix()
            recognition_error = ""
            score = None
            try:
                if overrides is not None:
                    result = {"text": overrides[str(source_path)].recognized_text, "score": overrides[str(source_path)].recognition_score}
                else:
                    result = recognizer.recognize(source_path)
                text, score = _normalize_recognition(
                    result
                )
                normalized, group_label, status = classify_text(
                    text,
                    score,
                    confidence_threshold,
                )
            except Exception as exc:  # one bad image must not abort the batch
                normalized = ""
                group_label = GROUP_REVIEW
                status = "recognition_error"
                recognition_error = str(exc)
                logger.warning("图片识别失败：%s：%s", source_path, exc)

            if overrides is not None:
                original = overrides[str(source_path)]
                normalized, group_label, status = original.recognized_text, original.group_label, original.status
                score, recognition_error = original.recognition_score, original.recognition_error
            filename = safe_output_filename(source_path, root, index)
            group_dir = grouped_root / _group_component(group_label)
            group_dir.mkdir(parents=True, exist_ok=True)
            destination = group_dir / filename
            source_stamp = file_stamp(source_path)
            old = previous_entries.get(str(source_path), {})
            if not isinstance(old, dict):
                old = {}
            old_path = previous_root / old.get('output', '')
            # Cache paths must remain inside the previous output directory.
            reusable = (old.get('source') == source_stamp and source_stamp is not None
                        and _is_relative_to(old_path.resolve(), previous_root)
                        and old.get('output_stamp') == file_stamp(old_path) and old_path.is_file())
            if reusable:
                clone_saved(old_path, destination)
            else:
                shutil.copy2(source_path, destination)
            thumb_name = hashlib.sha256(str(source_path).encode()).hexdigest() + '.png'
            thumb_dir = staging_dir / '.thumbnails'
            thumb_dir.mkdir(exist_ok=True)
            thumb_path = thumb_dir / thumb_name
            old_thumb = previous_root / '.thumbnails' / thumb_name
            if reusable and old.get('thumbnail_stamp') == file_stamp(old_thumb) and old_thumb.is_file():
                clone_saved(old_thumb, thumb_path)
            else:
                try:
                    data, _, _ = _thumbnail(destination)
                    thumb_path.write_bytes(data.getvalue())
                except (OSError, ValueError) as error:
                    logger.warning('缩略图生成失败：%s：%s', source_path, error)
            cache_entries[str(source_path)] = {'source': source_stamp,
                'output': destination.relative_to(staging_dir).as_posix(), 'thumbnail': thumb_name}
            record = GroupRecord(
                source_path=str(source_path),
                source_relative_path=relative,
                recognized_text=normalized,
                group_label=group_label,
                status=status,
                recognition_score=score,
                recognition_error=recognition_error,
                output_relative_path=destination.relative_to(staging_dir).as_posix(),
            )
            records.append(record)
            if progress:
                progress(index + 1, len(files), record)

        if cancelled and cancelled():
            raise GroupingCancelled()
        _write_manifest(staging_dir, records)
        assets_done = time.perf_counter()
        build_workbook(
            staging_dir / "字形归并.xlsx",
            records,
            asset_root=staging_dir,
            thumbnail_root=staging_dir / ".thumbnails",
        )
        if cancelled and cancelled():
            raise GroupingCancelled()
        for entry in cache_entries.values():
            entry['output_stamp'] = file_stamp(staging_dir / entry['output'])
            entry['thumbnail_stamp'] = file_stamp(staging_dir / '.thumbnails' / entry['thumbnail'])
        write_cache(staging_dir / '.save-cache.json', {'entries': cache_entries, 'workbook': file_stamp(staging_dir / '字形归并.xlsx')})
        _replace_output(staging_dir, output)
        staging_dir = None
        logger.info("归并保存耗时：图片/清单 %.3fs，Excel/发布 %.3fs",
                    assets_done - started, time.perf_counter() - assets_done)
    finally:
        if staging_dir is not None and staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)

    group_labels = {record.group_label for record in records}
    return {
        "output_dir": str(output),
        "record_count": len(records),
        "group_count": len(group_labels),
        "review_count": sum(
            1 for record in records if record.group_label == GROUP_REVIEW
        ),
        "unrecognized_count": sum(
            1
            for record in records
            if record.group_label == GROUP_UNRECOGNIZED
        ),
    }


def _thumbnail(path: Path, max_side: int = 88) -> tuple[io.BytesIO, int, int]:
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        data = io.BytesIO()
        image.save(data, format="PNG", optimize=False, compress_level=1)
        data.seek(0)
        return data, image.width, image.height


def _group_sort_key(label: str) -> tuple[int, str]:
    if label == GROUP_REVIEW:
        return 1, label
    if label == GROUP_UNRECOGNIZED:
        return 2, label
    return 0, label


def build_workbook(
    workbook_path: os.PathLike | str,
    records: Iterable[GroupRecord],
    *,
    asset_root: os.PathLike | str | None = None,
    thumbnail_root: os.PathLike | str | None = None,
) -> str:
    """生成按字一行、下一行标出处的 Excel 汇总。"""

    try:
        import xlsxwriter
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("未安装 xlsxwriter，无法生成 Excel") from exc

    records = list(records)
    root = _resolved(asset_root) if asset_root is not None else None
    groups: dict[str, list[GroupRecord]] = {}
    for record in records:
        groups.setdefault(record.group_label, []).append(record)
    for group in groups.values():
        group.sort(key=lambda record: record.source_relative_path)

    workbook_path = _resolved(workbook_path)
    workbook_path.parent.mkdir(parents=True, exist_ok=True)
    workbook = xlsxwriter.Workbook(
        str(workbook_path),
        {
            "strings_to_formulas": False,
            "strings_to_urls": False,
            "in_memory": True,
            "use_zip64": True,
        },
    )
    image_buffers = []
    try:
        sheet = workbook.add_worksheet("字形归并")
        sheet.hide_gridlines(2)
        sheet.set_column(0, 0, 12)
        label_format = workbook.add_format(
            {"bold": True, "font_size": 18, "align": "center", "valign": "vcenter", "border": 1}
        )
        source_label_format = workbook.add_format(
            {"bold": True, "align": "center", "valign": "vcenter", "border": 1, "bg_color": "#EAF2F8"}
        )
        image_format = workbook.add_format({"border": 1})
        source_format = workbook.add_format(
            {"font_size": 8, "text_wrap": True, "align": "center", "valign": "vcenter", "border": 1}
        )
        review_format = workbook.add_format(
            {"border": 1, "bg_color": "#FFF2CC"}
        )
        review_source_format = workbook.add_format(
            {"font_size": 8, "text_wrap": True, "align": "center", "valign": "vcenter", "border": 1, "bg_color": "#FFF2CC"}
        )
        row = 0
        for label in sorted(groups, key=_group_sort_key):
            records_for_group = groups[label]
            sheet.set_row(row, 92)
            sheet.set_row(row + 1, 52 if label not in {GROUP_REVIEW, GROUP_UNRECOGNIZED} else 78)
            sheet.write(row, 0, label, label_format)
            sheet.write(row + 1, 0, "出处", source_label_format)
            for column, record in enumerate(records_for_group, start=1):
                sheet.set_column(column, column, 14)
                image_path = (
                    root / record.output_relative_path
                    if root is not None
                    else _resolved(record.source_path)
                )
                try:
                    if thumbnail_root is None:
                        image_data, width, height = _thumbnail(image_path)
                    else:
                        thumb_name = hashlib.sha256(record.source_path.encode()).hexdigest() + '.png'
                        raw_thumbnail = (Path(thumbnail_root) / thumb_name).read_bytes()
                        image_data = io.BytesIO(raw_thumbnail)
                        with Image.open(image_data) as thumbnail:
                            width, height = thumbnail.size
                        image_data = io.BytesIO(raw_thumbnail)
                except Exception as exc:
                    logger.warning("Excel 缩略图生成失败：%s：%s", image_path, exc)
                    sheet.write(
                        row,
                        column,
                        f"图片无法读取：{record.recognition_error or exc}",
                        review_source_format,
                    )
                    sheet.write(
                        row + 1,
                        column,
                        record.source_relative_path,
                        review_source_format,
                    )
                    continue
                image_buffers.append(image_data)
                sheet.write_blank(
                    row,
                    column,
                    None,
                    review_format if label in {GROUP_REVIEW, GROUP_UNRECOGNIZED} else image_format,
                )
                sheet.insert_image(
                    row,
                    column,
                    image_path.name,
                    {
                        "image_data": image_data,
                        "x_offset": max(0, (96 - width) // 2),
                        "y_offset": max(0, (96 - height) // 2),
                        "object_position": 2,
                        "description": record.source_relative_path,
                    },
                )
                sheet.write(
                    row + 1,
                    column,
                    record.source_relative_path,
                    review_source_format if label in {GROUP_REVIEW, GROUP_UNRECOGNIZED} else source_format,
                )
            row += 2

        manifest_sheet = workbook.add_worksheet("清单")
        headers = [
            "分组", "识别文字", "状态", "识别置信度", "源文件相对路径",
            "源文件绝对路径", "输出相对路径", "识别错误",
        ]
        header_format = workbook.add_format({"bold": True, "bg_color": "#D9EAF7", "border": 1})
        body_format = workbook.add_format({"border": 1})
        for column, header in enumerate(headers):
            manifest_sheet.write(0, column, header, header_format)
        for row_index, record in enumerate(records, start=1):
            values = [
                record.group_label,
                record.recognized_text,
                record.status,
                record.recognition_score,
                record.source_relative_path,
                record.source_path,
                record.output_relative_path,
                record.recognition_error,
            ]
            for column, value in enumerate(values):
                manifest_sheet.write(row_index, column, value, body_format)
        manifest_sheet.freeze_panes(1, 0)
        manifest_sheet.autofilter(0, 0, len(records), len(headers) - 1)
        manifest_sheet.set_column(0, 3, 16)
        manifest_sheet.set_column(4, 7, 42)
    finally:
        workbook.close()
    return str(workbook_path)


def _default_output_dir(input_dir: Path) -> Path:
    return input_dir.parent / f"{input_dir.name}-grouped"


def _default_model_path() -> Path:
    from config import model_path
    return model_path()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="递归扫描图片，使用 PP-OCRv6 按字符归档并导出 Excel。"
    )
    parser.add_argument("--input", required=True, help="图片根目录")
    parser.add_argument("--input-format", choices=["auto", "crops", "images"], default="auto", help="自动选择切片 / 仅上游切片 / 所有图片")
    parser.add_argument("--output", help="输出目录，默认在输入目录旁生成")
    parser.add_argument("--model", help="PP-OCRv6 recognition inference.onnx")
    parser.add_argument("--yaml", help="模型同级 inference.yml")
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=DEFAULT_CONFIDENCE_THRESHOLD,
        help="低于该置信度的单字进入待复核，默认 0.70",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只扫描并打印图片数量，不加载模型、不写输出",
    )
    args = parser.parse_args(argv)
    input_dir = _resolved(args.input)
    output_dir = _resolved(args.output) if args.output else _default_output_dir(input_dir)
    try:
        files = iter_image_files(input_dir, excluded_dir=output_dir, input_format=args.input_format)
        if args.dry_run:
            print(f"发现图片：{len(files)} 张")
            return 0
        if not files:
            print("发现图片：0 张，跳过模型和输出")
            return 0
        if not 0.0 <= args.confidence_threshold <= 1.0:
            raise ValueError("--confidence-threshold 必须在 0 到 1 之间")
        model_path = _resolved(args.model) if args.model else _default_model_path()
        recognizer = PPOcrV6CharacterRecognizer(model_path, args.yaml)
        summary = run_grouping(
            input_dir,
            output_dir,
            recognizer,
            confidence_threshold=args.confidence_threshold,
            input_format=args.input_format,
        )
        print(
            "处理完成："
            f"{summary['record_count']} 张，"
            f"{summary['group_count']} 个分组，"
            f"{summary['review_count']} 张待复核，"
            f"{summary['unrecognized_count']} 张未识别。"
        )
        print(f"输出目录：{summary['output_dir']}")
        return 0
    except Exception as exc:
        print(f"处理失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
