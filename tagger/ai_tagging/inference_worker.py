from __future__ import annotations

import csv
import json
from pathlib import Path
import sys
from typing import Any

from . import cache


_PROTOCOL_PREFIX = b"TAGGER_AI:"


def _emit(message: dict[str, Any]) -> None:
    encoded = json.dumps(
        message, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    sys.stdout.buffer.write(_PROTOCOL_PREFIX + encoded + b"\n")
    sys.stdout.buffer.flush()


def _read_request() -> dict[str, Any]:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    if not isinstance(request, dict):
        raise ValueError("Invalid inference request.")
    return request


def _request_paths(request: dict[str, Any]) -> list[Path]:
    paths = request.get("image_paths")
    if not isinstance(paths, list) or not all(
        isinstance(path, str) for path in paths
    ):
        raise ValueError("Invalid image paths in inference request.")
    return [Path(path) for path in paths]


def _request_string(
    request: dict[str, Any], name: str, *, optional: bool = False
) -> str | None:
    value = request.get(name)
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Invalid {name} in inference request.")
    return value


def _request_threshold(request: dict[str, Any], name: str) -> float:
    value = request.get(name)
    if not isinstance(value, int | float) or not 0.0 <= value <= 1.0:
        raise ValueError(f"Invalid {name} in inference request.")
    return float(value)


def _run_inference(request: dict[str, Any]) -> None:
    image_paths = _request_paths(request)
    repo_id = _request_string(request, "repo_id")
    general_threshold = _request_threshold(request, "general_threshold")
    character_threshold = _request_threshold(request, "character_threshold")
    proxy = _request_string(request, "proxy", optional=True)
    cache_dir_value = _request_string(request, "cache_dir", optional=True)
    cache_dir = Path(cache_dir_value) if cache_dir_value is not None else None
    if repo_id is None:
        raise ValueError("Invalid repo_id in inference request.")

    import timm
    import torch
    from huggingface_hub import hf_hub_download
    from PIL import Image
    from timm.data.config import resolve_data_config
    from timm.data.transforms_factory import create_transform

    cache._configure_huggingface_proxy(proxy)
    _emit(
        {
            "type": "progress",
            "value": 0,
            "total": len(image_paths),
            "message": "Loading model...",
        }
    )
    model = timm.create_model(f"hf-hub:{repo_id}", cache_dir=cache_dir).eval()
    state_dict = timm.models.load_state_dict_from_hf(repo_id, cache_dir=cache_dir)
    model.load_state_dict(state_dict)
    transform = create_transform(
        **resolve_data_config(model.pretrained_cfg, model=model)
    )
    labels_path = hf_hub_download(
        repo_id=repo_id,
        filename="selected_tags.csv",
        cache_dir=cache_dir,
    )
    labels: list[tuple[str, int]] = []
    with open(labels_path, "r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            labels.append((row["name"], int(row["category"])))

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = model.to(device)
    for number, path in enumerate(image_paths, start=1):
        _emit(
            {
                "type": "progress",
                "value": number - 1,
                "total": len(image_paths),
                "message": path.name,
            }
        )
        with Image.open(path) as source:
            image = _prepare_image(source)
            inputs = transform(image).unsqueeze(0)[:, [2, 1, 0]].to(device)
        with torch.inference_mode():
            probabilities = torch.sigmoid(model(inputs)).squeeze(0).detach().cpu()
        matches: list[tuple[str, float]] = []
        for index, (name, category) in enumerate(labels):
            probability = float(probabilities[index])
            threshold = (
                general_threshold
                if category == 0
                else character_threshold
                if category == 4
                else None
            )
            if threshold is not None and probability >= threshold:
                matches.append((name.replace("_", " "), probability))
        matches.sort(key=lambda item: (-item[1], item[0].casefold(), item[0]))
        _emit({"type": "result", "path": str(path), "tags": matches})
        _emit(
            {
                "type": "progress",
                "value": number,
                "total": len(image_paths),
                "message": path.name,
            }
        )


def _prepare_image(image):
    from PIL import Image

    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "transparency" in image.info else "RGB")
    if image.mode == "RGBA":
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        background.alpha_composite(image)
        image = background.convert("RGB")
    width, height = image.size
    size = max(width, height)
    canvas = Image.new("RGB", (size, size), (255, 255, 255))
    canvas.paste(image, ((size - width) // 2, (size - height) // 2))
    return canvas


def main() -> int:
    try:
        _run_inference(_read_request())
    except Exception as exc:
        _emit({"type": "failed", "message": str(exc) or type(exc).__name__})
        return 1
    _emit({"type": "completed"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
