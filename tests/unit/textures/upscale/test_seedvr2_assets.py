"""Pin every default model download without network access or model allocation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from types import ModuleType

    from torch import Tensor


@pytest.fixture
def backend() -> ModuleType:
    return pytest.importorskip("gk3hd.textures.upscale.seedvr2", exc_type=ImportError)


pytestmark = [
    pytest.mark.slow,
    pytest.mark.filterwarnings("ignore:CUDA is not available or torch_xla is imported:UserWarning"),
]


def test_model_loading_pins_all_three_reviewed_assets(
    backend: ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    downloads: list[dict[str, object]] = []

    def download(**kwargs: object) -> str:
        downloads.append(kwargs)
        return str(tmp_path / str(kwargs["filename"]))

    class EmptyModel:
        @staticmethod
        def modules() -> tuple[()]:
            return ()

    monkeypatch.setattr(backend, "hf_hub_download", download)
    monkeypatch.setattr(backend, "_load_embedding", lambda *_args: object())
    monkeypatch.setattr(backend, "_load_model", lambda *_args, **_kwargs: EmptyModel())
    upscaler = backend.SeedVR2Upscaler(backend.SeedVR2Config(device="cpu", cache_dir=tmp_path))
    upscaler._ensure_loaded()
    upscaler._ensure_loaded()
    assert downloads == [
        {
            "repo_id": repository,
            "filename": filename,
            "revision": revision,
            "cache_dir": str(tmp_path),
            "tqdm_class": None,
        }
        for repository, filename, revision in (
            (
                "numz/SeedVR2_comfyUI",
                "seedvr2_ema_3b_fp16.safetensors",
                "09ced71023636e9bc8cdf9cdecfb2625d1e691e8",
            ),
            (
                "numz/SeedVR2_comfyUI",
                "ema_vae_fp16.safetensors",
                "09ced71023636e9bc8cdf9cdecfb2625d1e691e8",
            ),
            (
                "ByteDance-Seed/SeedVR2-3B",
                "pos_emb.pt",
                "37255ff8cccfb01071b87f635a5948ca8d53117c",
            ),
        )
    ]


def test_failed_pinned_download_restores_library_logging(
    backend: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(**_kwargs: object) -> str:
        message = "download interrupted"
        raise OSError(message)

    previous = backend.hugging_face_logging.get_verbosity()
    monkeypatch.setattr(backend, "hf_hub_download", fail)
    with pytest.raises(OSError, match="download interrupted"):
        backend._download(
            backend.MODEL_REPOSITORY,
            backend.DIT_FILENAME,
            None,
            None,
            revision=backend.MODEL_REVISION,
        )
    assert backend.hugging_face_logging.get_verbosity() == previous


def test_per_image_noise_is_independent_of_order_resume_and_global_rng(
    backend: ModuleType,
) -> None:
    """Exercise real noise/packing code, without loading the large DiT weights."""
    torch = backend.torch
    upscaler = backend.SeedVR2Upscaler(backend.SeedVR2Config(device="cpu"))
    upscaler._positive_embedding = torch.zeros((2, 4))

    # A zero prediction makes the returned latent the actual sampled noise.
    class ZeroPrediction:
        @staticmethod
        def parameters() -> Iterator[Tensor]:
            return iter((torch.zeros(1),))

        def __call__(self, *, vid: Tensor, **_kwargs: object) -> SimpleNamespace:
            return SimpleNamespace(vid_sample=torch.zeros_like(vid[..., :4]))

    upscaler._dit = ZeroPrediction()
    first = torch.zeros((1, 2, 3, 4))
    other = torch.zeros((1, 3, 5, 4))
    expected = upscaler._restore_latent(first)
    upscaler._restore_latent(other)
    torch.manual_seed(9876)
    torch.randn(137)
    assert torch.equal(upscaler._restore_latent(first), expected)

    resumed = backend.SeedVR2Upscaler(backend.SeedVR2Config(device="cpu"))
    resumed._dit = ZeroPrediction()
    resumed._positive_embedding = upscaler._positive_embedding
    assert torch.equal(resumed._restore_latent(first), expected)
    different_seed = backend.SeedVR2Upscaler(backend.SeedVR2Config(device="cpu", seed=43))
    different_seed._dit = ZeroPrediction()
    different_seed._positive_embedding = upscaler._positive_embedding
    assert not torch.equal(different_seed._restore_latent(first), expected)
