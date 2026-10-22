"""Pin every default model download without network access or model allocation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from gk3hd.textures.upscale._offload import enable_block_offload

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


@pytest.mark.parametrize(("device", "expected_index"), [("cuda", None), ("cuda:2", 2)])
def test_movie_memory_cap_accepts_default_and_explicit_gpu(
    backend: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    device: str,
    expected_index: int | None,
) -> None:
    torch = backend.torch
    limits: list[tuple[float, int | None]] = []
    monkeypatch.setattr(backend, "_resolve_device", lambda _name: torch.device(device))
    monkeypatch.setattr(backend, "_compute_dtype", lambda _device: torch.float16)
    monkeypatch.setattr(
        torch.cuda,
        "set_per_process_memory_fraction",
        lambda fraction, index: limits.append((fraction, index)),
    )
    backend.SeedVR2Upscaler(backend.SeedVR2Config(gpu_memory_fraction=0.85))
    assert limits == [(0.85, expected_index)]


def test_stage_offloading_releases_inactive_weights_before_loading_active_weights(
    backend: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    torch = backend.torch
    events: list[tuple[str, str]] = []
    monkeypatch.setattr(backend, "_resolve_device", lambda _name: torch.device("cuda"))
    monkeypatch.setattr(backend, "_compute_dtype", lambda _device: torch.float16)
    monkeypatch.setattr(torch.cuda, "empty_cache", lambda: events.append(("cache", "released")))

    class Stage:
        def __init__(self, name: str) -> None:
            self.name = name

        def to(self, *, device: object) -> None:
            events.append((self.name, str(device)))

    upscaler = backend.SeedVR2Upscaler(backend.SeedVR2Config(offload_inactive_models=True))
    upscaler._dit, upscaler._vae = Stage("dit"), Stage("vae")
    upscaler._activate_model("vae")
    upscaler._activate_model("dit")
    assert events == [
        ("dit", "cpu"),
        ("cache", "released"),
        ("vae", "cuda"),
        ("vae", "cpu"),
        ("cache", "released"),
        ("dit", "cuda"),
    ]


def test_block_offloading_does_not_change_forward_values_or_parameter_precision(
    backend: ModuleType,
) -> None:
    torch = backend.torch

    class Transformer(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.blocks = torch.nn.ModuleList([torch.nn.Linear(3, 3) for _ in range(2)])

        def forward(self, value: Tensor) -> Tensor:
            for block in self.blocks:
                value = block(value)
            return value

    model = Transformer()
    value = torch.tensor([[1.0, 2.0, 3.0]])
    expected = model(value)
    weights = {name: parameter.detach().clone() for name, parameter in model.named_parameters()}
    enable_block_offload(model, torch.device("cpu"))
    assert torch.equal(model(value), expected)
    assert all(
        torch.equal(parameter, weights[name]) for name, parameter in model.named_parameters()
    )
    assert all(parameter.dtype == torch.float32 for parameter in model.parameters())


def test_block_offloading_preserves_gpu_inference_values(backend: ModuleType) -> None:
    torch = backend.torch
    if not torch.cuda.is_available():
        pytest.skip("CUDA is unavailable")

    class Transformer(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.blocks = torch.nn.ModuleList([torch.nn.Linear(8, 8) for _ in range(2)])

        def forward(self, value: Tensor) -> Tensor:
            for block in self.blocks:
                value = block(value)
            return value

    device = torch.device("cuda", torch.cuda.current_device())
    with torch.inference_mode():
        model = Transformer().to(device=device, dtype=torch.float16)
        value = torch.ones((3, 8), device=device, dtype=torch.float16)
        expected = model(value)
        enable_block_offload(model, device)
        assert torch.equal(model(value), expected)
        assert all(parameter.device.type == "cpu" for parameter in model.parameters())


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
