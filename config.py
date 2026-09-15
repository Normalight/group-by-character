"""内部配置：模型和导入方式不暴露给界面用户。"""
from pathlib import Path
import sys

MODEL_RELATIVE_PATH = Path('models/ppocrv6_rec/small/inference.onnx')
DEFAULT_INPUT_FORMAT = 'auto'


def resource_root():
    """源码目录或 PyInstaller 内置资源目录。"""
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))


def model_path():
    return resource_root() / MODEL_RELATIVE_PATH


def dictionary_path():
    return model_path().with_name('inference.yml')


def application_dir():
    if sys.platform == 'darwin' and getattr(sys, 'frozen', False):
        return Path.home() / 'Documents' / '字形归并工具'
    return Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
