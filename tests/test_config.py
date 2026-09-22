from pathlib import Path
import sys
import config
from grouping.service import _default_model_path


def test_default_model_is_local_and_independent_of_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    expected = Path(config.__file__).resolve().parent / config.MODEL_RELATIVE_PATH
    assert _default_model_path() == expected
    assert expected.is_file()
    assert config.dictionary_path().is_file()


def test_frozen_model_uses_bundle_resources(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    assert config.model_path() == tmp_path / config.MODEL_RELATIVE_PATH
    assert config.dictionary_path() == (tmp_path / config.MODEL_RELATIVE_PATH).with_name('inference.yml')
