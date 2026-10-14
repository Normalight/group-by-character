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

import runpy
protection = runpy.run_path(str(Path(project_dir) / 'packaging/protection.py'))
code_root = protection['prepare'](project_dir)
native_release = runpy.run_path(str(Path(project_dir) / 'packaging/native_release.py'))
datas.extend(native_release['analysis_data'](project_dir))
datas.append(protection['build_info'](project_dir))
# The compiled shared package reads products.json next to its module at
# runtime; ship the registry from the installed wheel alongside it.
import hanzi_update
datas.append((str(Path(hanzi_update.__file__).parent / 'products.json'), 'hanzi_update'))

a = Analysis([str(code_root / 'packaging/entry.py')], pathex=[str(code_root), str(code_root / 'packaging')],
             binaries=[], datas=datas, hiddenimports=['yaml', 'xlsxwriter', '_cffi_backend'],
             hookspath=[], runtime_hooks=[], excludes=[], noarchive=False)
# 沿用上游的 Windows ICU 兼容处理，保留 Qt 自身目录中的依赖。
def incompatible_root_icu(entry):
    destination = os.path.normpath(entry[0])
    name = os.path.basename(destination).lower()
    return os.path.dirname(destination) in ('', '.') and (
        name == 'icuuc.dll' or (name.startswith('icudt') and name.endswith('.dll')))

a.binaries = [entry for entry in a.binaries if not incompatible_root_icu(entry)]
protection['apply'](a, code_root)
windows_bundle = runpy.run_path(str(project_dir / 'packaging/windows_bundle.py'))
windows_bundle['apply'](a, project_dir / 'build/windows-bundle-report.json')
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='group_by_character',
          debug=False, strip=False, upx=False, console=False,
          version=native_release['exe_version'](project_dir))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='group_by_character')
