"""Optional save accelerators. Invalid/missing caches always trigger regeneration."""
import json
import os
import uuid


def file_stamp(path):
    try:
        stat = os.stat(path)
        return [stat.st_size, stat.st_mtime_ns, stat.st_ino]
    except (OSError, TypeError):
        return None


def read_cache(path):
    try:
        with open(path, encoding='utf-8') as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def write_cache(path, value):
    temporary = str(path) + '.tmp-' + uuid.uuid4().hex
    try:
        with open(temporary, 'w', encoding='utf-8') as stream:
            json.dump(value, stream)
        os.replace(temporary, path)
    except OSError:
        pass
    finally:
        try:
            os.unlink(temporary)
        except OSError:
            pass


def clone_saved(source, destination):
    # Only saved assets are linked; never link mutable input images.
    import shutil
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def unchanged_export(output, records):
    from pathlib import Path
    from dataclasses import asdict
    root = Path(output).resolve()
    cache = read_cache(root / '.save-cache.json')
    manifest = read_cache(root / '归并清单.json')
    if manifest.get('records') != [asdict(record) for record in records]:
        return False
    if (not (root / '字形归并.xlsx').is_file()
            or cache.get('workbook') != file_stamp(root / '字形归并.xlsx')):
        return False
    entries = cache.get('entries', {})
    if not isinstance(entries, dict):
        return False
    for record in records:
        entry = entries.get(record.source_path, {})
        if not isinstance(entry, dict):
            return False
        asset = root / entry.get('output', '')
        thumbnail = root / '.thumbnails' / entry.get('thumbnail', '')
        if (not asset.is_file() or not thumbnail.is_file()
                or not asset.resolve().is_relative_to(root)
                or not thumbnail.resolve().is_relative_to(root)
                or entry.get('source') != file_stamp(record.source_path)
                or entry.get('output_stamp') != file_stamp(asset)
                or entry.get('thumbnail_stamp') != file_stamp(thumbnail)):
            return False
    return bool(cache)
