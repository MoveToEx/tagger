from __future__ import annotations

import csv
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import cache


class _InferenceWorker(QObject):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        image_paths: list[Path],
        repo_id: str,
        general_threshold: float,
        character_threshold: float,
        proxy: str | None,
        cache_dir: Path | None = None,
    ) -> None:
        super().__init__()
        self.image_paths = image_paths
        self.repo_id = repo_id
        self.general_threshold = general_threshold
        self.character_threshold = character_threshold
        self.proxy = proxy
        self.cache_dir = cache_dir

    def run(self) -> None:
        try:
            results = self._run_inference()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.completed.emit(results)

    def _run_inference(self) -> dict[str, list[tuple[str, float]]]:
        import timm
        import torch
        from huggingface_hub import hf_hub_download
        from PIL import Image
        from timm.data.config import resolve_data_config
        from timm.data.transforms_factory import create_transform

        cache._configure_huggingface_proxy(self.proxy)
        self.progress.emit(0, len(self.image_paths), "Loading model...")
        model = timm.create_model(
            f"hf-hub:{self.repo_id}", cache_dir=self.cache_dir
        ).eval()
        state_dict = timm.models.load_state_dict_from_hf(
            self.repo_id, cache_dir=self.cache_dir
        )
        model.load_state_dict(state_dict)
        transform = create_transform(
            **resolve_data_config(model.pretrained_cfg, model=model)
        )
        labels_path = hf_hub_download(
            repo_id=self.repo_id,
            filename="selected_tags.csv",
            cache_dir=self.cache_dir,
        )
        labels: list[tuple[str, int]] = []
        with open(labels_path, "r", encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                labels.append((row["name"], int(row["category"])))

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model = model.to(device)
        results: dict[str, list[tuple[str, float]]] = {}
        for number, path in enumerate(self.image_paths, start=1):
            self.progress.emit(number - 1, len(self.image_paths), path.name)
            with Image.open(path) as source:
                image = _prepare_image(source)
                inputs = transform(image).unsqueeze(0)[:, [2, 1, 0]].to(device)
            with torch.inference_mode():
                probabilities = torch.sigmoid(model(inputs)).squeeze(0).detach().cpu()
            matches: list[tuple[str, float]] = []
            for index, (name, category) in enumerate(labels):
                probability = float(probabilities[index])
                threshold = (
                    self.general_threshold
                    if category == 0
                    else self.character_threshold
                    if category == 4
                    else None
                )
                if threshold is not None and probability >= threshold:
                    matches.append((name.replace("_", " "), probability))
            matches.sort(key=lambda item: (-item[1], item[0].casefold(), item[0]))
            results[str(path)] = matches
            self.progress.emit(number, len(self.image_paths), path.name)
        return results


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
