"""单字图片识别：PP-OCRv6 ONNX 预处理及 CTC 解码。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image


def decode_ctc_predictions(
    predictions,
    character: list[str],
) -> tuple[str, Optional[float]]:
    """对单张 v6 输出做 CTC greedy decode，返回文字和 token 平均置信度。"""

    logits = np.asarray(predictions, dtype=np.float32)
    if logits.ndim == 3:
        if logits.shape[0] != 1:
            raise ValueError(f"单图输出 batch 维度无效：{logits.shape}")
        logits = logits[0]
    if logits.ndim != 2 or logits.shape[1] <= 0:
        raise ValueError(f"识别输出形状无效：{logits.shape}")
    row_sums = logits.sum(axis=1)
    if np.all(logits >= 0) and np.allclose(row_sums, 1.0, atol=1e-3):
        probabilities = logits
    else:
        shifted = logits - logits.max(axis=1, keepdims=True)
        exponent = np.exp(shifted)
        probabilities = exponent / exponent.sum(axis=1, keepdims=True)
    indices = probabilities.argmax(axis=1)
    limit = min(probabilities.shape[1], len(character))
    output = []
    scores = []
    previous = 0
    for time_index, index_value in enumerate(indices):
        index = int(index_value)
        if index == 0:
            previous = 0
            continue
        if index == previous:
            continue
        if index < limit:
            output.append(character[index])
            scores.append(float(probabilities[time_index, index]))
        previous = index
    return "".join(output), (sum(scores) / len(scores) if scores else None)



class PPOcrV6CharacterRecognizer:
    """面向单字图片的 PP-OCRv6 recognition ONNX 包装。"""

    image_height = 48
    max_width = 3200

    def __init__(self, model_path: os.PathLike | str, yaml_path=None):
        import onnxruntime as ort
        import yaml

        model = Path(model_path).expanduser().resolve()
        if not model.is_file():
            raise FileNotFoundError(f"v6 识别模型不存在：{model}")
        config_path = (
            Path(yaml_path).expanduser().resolve()
            if yaml_path is not None
            else model.with_name("inference.yml")
        )
        if not config_path.is_file():
            raise FileNotFoundError(f"v6 字典配置不存在：{config_path}")
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        try:
            dictionary = config["PostProcess"]["character_dict"]
        except (KeyError, TypeError) as exc:
            raise ValueError(f"v6 字典配置无效：{config_path}") from exc
        self.character = ["<blank>"] + list(dictionary)
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(
            str(model),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name

    def _preprocess(self, image: Image.Image) -> np.ndarray:
        image = image.convert("RGB")
        width, height = image.size
        if width <= 0 or height <= 0:
            raise ValueError(f"图片尺寸无效：{width}x{height}")
        resized_width = max(
            1,
            min(
                self.max_width,
                int(round(self.image_height * width / float(height))),
            ),
        )
        resized = image.resize(
            (resized_width, self.image_height),
            Image.Resampling.BILINEAR,
        )
        rgb = np.asarray(resized, dtype=np.uint8)
        bgr = rgb[:, :, ::-1]
        array = bgr.astype(np.float32)
        array *= 1.0 / 127.5
        array -= 1.0
        return np.ascontiguousarray(array.transpose(2, 0, 1)[None])

    def recognize(self, image_path: os.PathLike | str) -> dict:
        image_file = Path(image_path).expanduser().resolve()
        with Image.open(image_file) as image:
            tensor = self._preprocess(image)
        predictions = self.session.run(
            [self.output_name],
            {self.input_name: tensor},
        )[0]
        text, score = decode_ctc_predictions(predictions, self.character)
        return {"text": text, "score": score}

