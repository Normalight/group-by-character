# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os

project_dir = Path(SPECPATH)
model_dir = Path('models/ppocrv6_rec/small')
datas = []
for filename in ('inference.onnx', 'inference.yml'):
    source = project_dir / model_dir / filename
    if not source.is_file():
        raise FileNotFoundError(f'缺少内置模型资源：{source}')
    datas.append((str(source), model_dir.as_posix()))

a = Analysis([str(project_dir / 'packaging/entry.py')], pathex=[str(project_dir), str(project_dir / 'packaging')],
             binaries=[], datas=datas, hiddenimports=['yaml', 'xlsxwriter'],
             hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
# 沿用上游的 Windows ICU 兼容处理，保留 Qt 自身目录中的依赖。
def incompatible_root_icu(entry):
    destination = os.path.normpath(entry[0])
    name = os.path.basename(destination).lower()
    return os.path.dirname(destination) in ('', '.') and (
        name == 'icuuc.dll' or (name.startswith('icudt') and name.endswith('.dll')))

a.binaries = [entry for entry in a.binaries if not incompatible_root_icu(entry)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='group_by_character',
          debug=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='group_by_character')
