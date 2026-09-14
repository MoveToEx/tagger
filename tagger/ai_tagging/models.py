from __future__ import annotations

from dataclasses import dataclass


TAGGING_MODEL_TYPE = "Tagging"
VAE_MODEL_TYPE = "VAE"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    repo_id: str
    model_type: str
    filename: str | None = None

    @property
    def required_files(self) -> tuple[str, ...]:
        if self.filename is not None:
            return (self.filename,)
        return ("config.json", "selected_tags.csv")


MODEL_REPOSITORIES = {
    "ViT": "SmilingWolf/wd-vit-tagger-v3",
    "ViT Large": "SmilingWolf/wd-vit-large-tagger-v3",
    "SwinV2": "SmilingWolf/wd-swinv2-tagger-v3",
    "ConvNeXt": "SmilingWolf/wd-convnext-tagger-v3",
}
QWEN_IMAGE_VAE = ModelSpec(
    "Qwen Image VAE",
    "circlestone-labs/Anima",
    VAE_MODEL_TYPE,
    "split_files/vae/qwen_image_vae.safetensors",
)
MODEL_SPECS = (
    *(
        ModelSpec(name, repo_id, TAGGING_MODEL_TYPE)
        for name, repo_id in MODEL_REPOSITORIES.items()
    ),
    QWEN_IMAGE_VAE,
)
AI_DEPENDENCIES = ("huggingface_hub", "numpy", "pandas", "PIL", "timm", "torch")
VAE_DEPENDENCIES = (
    "diffusers",
    "huggingface_hub",
    "numpy",
    "PIL",
    "safetensors",
    "torch",
)
