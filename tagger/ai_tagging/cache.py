from __future__ import annotations

from pathlib import Path

from tagger.paths import get_model_directory


def _user_model_cache_directory() -> Path:
    from huggingface_hub.constants import HF_HUB_CACHE

    return Path(HF_HUB_CACHE)


def _repo_cache_path(repo_id: str, cache_dir: Path | None = None) -> Path:
    directory = cache_dir or _user_model_cache_directory()
    return directory / f"models--{repo_id.replace('/', '--')}"


def _model_is_cached(repo_id: str, cache_dir: Path | None = None) -> bool:
    snapshots = _repo_cache_path(repo_id, cache_dir) / "snapshots"
    if not snapshots.is_dir():
        return False
    return any(
        (snapshot / "config.json").is_file()
        and (snapshot / "selected_tags.csv").is_file()
        for snapshot in snapshots.iterdir()
        if snapshot.is_dir()
    )


def _cached_model_locations(repo_id: str) -> list[str]:
    user_directory = _user_model_cache_directory()
    local_directory = get_model_directory()
    locations = []
    if _model_is_cached(repo_id, user_directory):
        locations.append("User home")
    if local_directory != user_directory and _model_is_cached(
        repo_id, local_directory
    ):
        locations.append("Local data")
    return locations


def _preferred_model_cache_directory(repo_id: str) -> Path | None:
    local_directory = get_model_directory()
    if _model_is_cached(repo_id, local_directory):
        return local_directory
    return None


def _configure_huggingface_proxy(proxy: str | None) -> None:
    import httpx
    from huggingface_hub import set_client_factory

    proxy_url = (proxy.strip() or None) if proxy is not None else None
    set_client_factory(
        lambda: httpx.Client(
            proxy=proxy_url,
            follow_redirects=True,
            timeout=None,
            trust_env=proxy is None,
        )
    )
