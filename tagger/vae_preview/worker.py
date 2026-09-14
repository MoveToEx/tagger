from __future__ import annotations

import json
import importlib
from pathlib import Path
import sys
from typing import Any


_PROTOCOL_PREFIX = "TAGGER_VAE:"


def _emit(message: dict[str, object]) -> None:
    print(_PROTOCOL_PREFIX + json.dumps(message, ensure_ascii=False), flush=True)


def _load_model(configuration: dict[str, object]) -> tuple[Any, Any, Any]:
    from huggingface_hub import hf_hub_download
    import torch

    AutoencoderKLQwenImage = getattr(
        importlib.import_module("diffusers"), "AutoencoderKLQwenImage"
    )

    repo_id = configuration.get("repo_id")
    filename = configuration.get("filename")
    cache_dir = configuration.get("cache_dir")
    if not isinstance(repo_id, str) or not isinstance(filename, str):
        raise ValueError("The VAE model configuration is invalid.")
    if cache_dir is not None and not isinstance(cache_dir, str):
        raise ValueError("The VAE cache directory is invalid.")

    model_path = hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        cache_dir=cache_dir,
        local_files_only=True,
    )
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    dtype = torch.float32
    if device.type == "cuda":
        dtype = (
            torch.bfloat16
            if torch.cuda.is_bf16_supported()
            else torch.float16
        )
    from safetensors.torch import load_file

    vae = AutoencoderKLQwenImage()
    state_dict = load_file(model_path)
    for prefix in ("vae.", "first_stage_model.", "model."):
        if state_dict and all(key.startswith(prefix) for key in state_dict):
            state_dict = {
                key.removeprefix(prefix): value
                for key, value in state_dict.items()
            }
            break
    expected_keys = set(vae.state_dict())
    if set(state_dict) != expected_keys:
        converter = getattr(
            importlib.import_module("diffusers.loaders.single_file_utils"),
            "convert_wan_vae_to_diffusers",
        )
        state_dict = converter(state_dict)
    incompatible = vae.load_state_dict(state_dict, strict=False)
    if incompatible.missing_keys or incompatible.unexpected_keys:
        missing = ", ".join(incompatible.missing_keys[:5])
        unexpected = ", ".join(incompatible.unexpected_keys[:5])
        raise RuntimeError(
            "The downloaded VAE weights do not match AutoencoderKLQwenImage. "
            f"Missing keys: {missing or 'none'}. "
            f"Unexpected keys: {unexpected or 'none'}."
        )
    vae.to(device=device, dtype=dtype)
    vae.eval()
    vae.enable_tiling()
    return vae, torch, device


def _decode_image(
    vae: Any,
    torch: Any,
    device: Any,
    image_path: Path,
    output_path: Path,
) -> None:
    from PIL import Image, ImageOps
    import numpy as np

    with Image.open(image_path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    width, height = image.size
    padded_width = ((width + 7) // 8) * 8
    padded_height = ((height + 7) // 8) * 8
    if (padded_width, padded_height) != image.size:
        padded = Image.new("RGB", (padded_width, padded_height))
        padded.paste(image, (0, 0))
        if padded_width > width:
            edge = image.crop((width - 1, 0, width, height))
            padded.paste(edge.resize((padded_width - width, height)), (width, 0))
        if padded_height > height:
            edge = padded.crop((0, height - 1, padded_width, height))
            padded.paste(
                edge.resize((padded_width, padded_height - height)), (0, height)
            )
        image = padded

    values = np.asarray(image, dtype=np.float32) / 127.5 - 1.0
    sample = torch.from_numpy(values).permute(2, 0, 1).unsqueeze(0).unsqueeze(2)
    dtype = next(vae.parameters()).dtype
    sample = sample.to(device=device, dtype=dtype)
    with torch.inference_mode():
        latent = vae.encode(sample).latent_dist.mode()
        decoded = vae.decode(latent, return_dict=False)[0]
    if decoded.ndim == 5:
        decoded = decoded[:, :, 0]
    decoded = decoded[0, :, :height, :width]
    decoded = (
        decoded.float().clamp(-1, 1).add(1).mul(127.5).byte()
        .permute(1, 2, 0).cpu().numpy()
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(decoded, mode="RGB").save(output_path, format="PNG")


def main() -> int:
    first_line = sys.stdin.readline()
    if not first_line:
        raise ValueError("No VAE configuration was provided.")
    configuration = json.loads(first_line)
    if not isinstance(configuration, dict) or configuration.get("type") != "configure":
        raise ValueError("The VAE model configuration is invalid.")
    _emit({"type": "progress", "request_id": -1, "message": "Loading VAE..."})
    vae, torch, device = _load_model(configuration)
    _emit({"type": "ready"})

    for line in sys.stdin:
        message: dict[str, object] = {}
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError("Invalid request.")
            if message.get("type") == "shutdown":
                return 0
            if message.get("type") != "decode":
                raise ValueError("Invalid request.")
            request_id = message.get("request_id")
            image_path = message.get("image_path")
            output_path = message.get("output_path")
            if (
                not isinstance(request_id, int)
                or not isinstance(image_path, str)
                or not isinstance(output_path, str)
            ):
                raise ValueError("Invalid request.")
            _emit(
                {
                    "type": "progress",
                    "request_id": request_id,
                    "message": "Encoding and decoding image...",
                }
            )
            _decode_image(
                vae, torch, device, Path(image_path), Path(output_path)
            )
            _emit(
                {
                    "type": "result",
                    "request_id": request_id,
                    "image_path": image_path,
                    "output_path": output_path,
                }
            )
        except Exception as exc:
            request_id = message.get("request_id", -1)
            _emit(
                {
                    "type": "failed",
                    "request_id": request_id if isinstance(request_id, int) else -1,
                    "message": str(exc),
                }
            )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _emit({"type": "failed", "request_id": -1, "message": str(exc)})
        raise SystemExit(1) from exc
