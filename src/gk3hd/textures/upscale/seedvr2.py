"""Minimal, lazy SeedVR2 3B image inference.

The public backend downloads three files through ``huggingface_hub`` on first
use, builds the vendored 3B DiT and VAE on PyTorch's meta device, and assigns
SafeTensors weights directly to the selected device.  It implements only the
quality path used for GK3: one distilled step, CFG 1, SDPA, seed 42, and numz's
LAB correction with luminance weight 0.8.
"""

from __future__ import annotations

import gc
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import torch
import torch.nn.functional
from huggingface_hub import hf_hub_download
from huggingface_hub.utils import logging as hugging_face_logging
from PIL import Image
from safetensors.torch import load_file

from gk3hd.textures._vendor.seedvr2.models.dit_3b import na
from gk3hd.textures._vendor.seedvr2.models.dit_3b.nadit import NaDiT
from gk3hd.textures._vendor.seedvr2.models.video_vae_v3.modules.attn_video_vae import (
    VideoAutoencoderKLWrapper,
)
from gk3hd.textures.progress import hugging_face_progress_class
from gk3hd.textures.upscale._lab import lab_color_transfer

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Protocol

    from torch import Tensor, nn

    from gk3hd.textures.progress import DownloadProgress

    class _AttentionModule(Protocol):
        """Attributes customized on the vendored attention implementation."""

        attention_mode: str
        compute_dtype: torch.dtype


MODEL_REPOSITORY = "numz/SeedVR2_comfyUI"
EMBEDDING_REPOSITORY = "ByteDance-Seed/SeedVR2-3B"
# Immutable snapshots used by the reviewed pipeline, not the moving main branch.
# Changing these or the inference defaults also requires a GENERATION_REVISION bump.
MODEL_REVISION = "09ced71023636e9bc8cdf9cdecfb2625d1e691e8"
EMBEDDING_REVISION = "37255ff8cccfb01071b87f635a5948ca8d53117c"
DIT_FILENAME = "seedvr2_ema_3b_fp16.safetensors"
VAE_FILENAME = "ema_vae_fp16.safetensors"
POSITIVE_EMBEDDING_FILENAME = "pos_emb.pt"
VAE_SCALING_FACTOR = 0.9152
IMAGE_LATENT_DIMENSIONS = 4
RGB_CHANNELS = 3


@dataclass(frozen=True, slots=True)
class SeedVR2Config:
    """Quality and storage settings for the supported SeedVR2 3B path."""

    device: str = "auto"
    seed: int = 42
    cache_dir: Path | None = None
    dit_path: Path | None = None
    vae_path: Path | None = None
    positive_embedding_path: Path | None = None
    # Spatial VAE inference tiling limits peak GPU memory. It is unrelated to
    # whether a GK3 texture repeats across a surface (``TextureFeatures.tiled``).
    vae_spatial_tiling: bool = True
    vae_spatial_tile_size: int = 1024
    vae_spatial_tile_overlap: int = 128
    lab_luminance_weight: float = 0.8
    edge_antialias_strength: float = 0.2

    def __post_init__(self) -> None:
        """Reject settings outside the tested one-step 4x implementation."""
        if self.vae_spatial_tile_size <= 0:
            msg = "vae_spatial_tile_size must be positive"
            raise ValueError(msg)
        if not 0 <= self.vae_spatial_tile_overlap < self.vae_spatial_tile_size:
            msg = (
                "vae_spatial_tile_overlap must be non-negative and smaller than "
                "vae_spatial_tile_size"
            )
            raise ValueError(msg)
        if not 0.0 <= self.lab_luminance_weight <= 1.0:
            msg = "lab_luminance_weight must be between 0 and 1"
            raise ValueError(msg)
        if not 0.0 <= self.edge_antialias_strength <= 1.0:
            msg = "edge_antialias_strength must be between 0 and 1"
            raise ValueError(msg)


class SeedVR2Upscaler:
    """Reusable SeedVR2 3B backend with lazy model download and loading.

    Constructing the object is cheap. The first call to :meth:`upscale` obtains
    model files and materializes weights; later calls reuse both models.
    """

    scale = 4

    def __init__(
        self,
        config: SeedVR2Config | None = None,
        *,
        download_progress: DownloadProgress | None = None,
    ) -> None:
        """Store configuration without downloading or allocating either model."""
        self.config = config or SeedVR2Config()
        self.download_progress = download_progress
        self.device = _resolve_device(self.config.device)
        self.compute_dtype = _compute_dtype(self.device)
        self._dit: NaDiT | None = None
        self._vae: VideoAutoencoderKLWrapper | None = None
        self._positive_embedding: Tensor | None = None

    def upscale(self, image: Image.Image) -> Image.Image:
        """Upscale one RGB image exactly 4x and apply LAB color correction."""
        self._ensure_loaded()
        source, reference, true_size = self._prepare_image(image)
        with torch.inference_mode():
            latent = self._encode(source)
            restored = self._restore_latent(latent)
            generated = self._decode(restored)
            true_width, true_height = true_size
            generated = generated[:, :, :true_height, :true_width]
            reference = reference[:, :, :true_height, :true_width]
            corrected = lab_color_transfer(
                generated,
                reference,
                luminance_weight=self.config.lab_luminance_weight,
            )
        array = (
            corrected[0]
            .permute(1, 2, 0)
            .float()
            .add_(1.0)
            .mul_(127.5)
            .add_(0.5)
            .clamp_(0, 255)
            .byte()
            .cpu()
            .numpy()
        )
        if self.config.edge_antialias_strength:
            array = _edge_antialias(array, self.config.edge_antialias_strength)
        return Image.fromarray(array, mode="RGB")

    @property
    def device_description(self) -> str:
        """Return a concise user-facing description of the selected compute device."""
        if self.device.type == "cuda":
            return f"CUDA ({torch.cuda.get_device_name(self.device)})"
        if self.device.type == "mps":
            return "Apple Metal"
        return "CPU"

    def _prepare_image(self, image: Image.Image) -> tuple[Tensor, Tensor, tuple[int, int]]:
        """Convert, resize 4x, pad to 16, and normalize an input image."""
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8).copy()
        tensor = torch.from_numpy(rgb).permute(2, 0, 1).unsqueeze(0).to(self.device)
        tensor = tensor.to(torch.float32).div_(255.0)
        true_height = image.height * self.scale
        true_width = image.width * self.scale
        resized = torch.nn.functional.interpolate(
            tensor,
            size=(true_height, true_width),
            mode="bicubic",
            align_corners=False,
            antialias=True,
        ).clamp_(0.0, 1.0)
        pad_height = (-true_height) % 16
        pad_width = (-true_width) % 16
        if pad_height or pad_width:
            resized = torch.nn.functional.pad(resized, (0, pad_width, 0, pad_height))
        normalized = resized.mul(2.0).sub_(1.0).to(self.compute_dtype)
        return normalized, normalized.clone(), (true_width, true_height)

    def _encode(self, source: Tensor) -> Tensor:
        """Encode BCHW RGB to SeedVR2's channels-last single-frame latent."""
        vae = _require(self._vae, "VAE")
        tile = (self.config.vae_spatial_tile_size, self.config.vae_spatial_tile_size)
        overlap = (self.config.vae_spatial_tile_overlap, self.config.vae_spatial_tile_overlap)
        encoded = vae.encode(
            cast("torch.FloatTensor", source),
            tiled=self.config.vae_spatial_tiling,
            tile_size=tile,
            tile_overlap=overlap,
        ).latent
        if encoded.ndim == IMAGE_LATENT_DIMENSIONS:
            encoded = encoded.unsqueeze(2)
        return encoded.permute(0, 2, 3, 4, 1)[0].mul(VAE_SCALING_FACTOR)

    def _restore_latent(self, latent: Tensor) -> Tensor:
        """Run the distilled one-step DiT; at t=T Euler reduces to noise-prediction."""
        dit = _require(self._dit, "DiT")
        positive = _require(self._positive_embedding, "positive embedding")
        torch.manual_seed(self.config.seed)
        noise = torch.randn_like(latent, dtype=self.compute_dtype)
        # Numz creates an augmentation draw even when latent noise is disabled.
        # It has no effect on the result, so the minimal path intentionally omits it.
        condition = torch.zeros((*latent.shape[:-1], latent.shape[-1] + 1), **_like(latent))
        condition[..., :-1] = latent
        condition[..., -1:] = 1.0
        noise_flat, latent_shape = na.flatten([cast("torch.FloatTensor", noise)])
        condition_flat, _ = na.flatten([cast("torch.FloatTensor", condition)])
        text_flat, text_shape = na.flatten([cast("torch.FloatTensor", positive)])
        timestep = torch.full((1,), 1000.0, **_like(noise))
        kwargs = {
            "vid": torch.cat([noise_flat, condition_flat], dim=-1),
            "txt": text_flat,
            "vid_shape": latent_shape,
            "txt_shape": text_shape,
            "timestep": timestep,
        }
        model_dtype = next(dit.parameters()).dtype
        use_autocast = self.device.type == "cuda" and model_dtype != self.compute_dtype
        with torch.autocast(
            self.device.type,
            dtype=self.compute_dtype,
            enabled=use_autocast,
        ):
            prediction = dit(**kwargs).vid_sample
        restored = noise_flat - prediction
        return na.unflatten(restored, latent_shape)[0]

    def _decode(self, latent: Tensor) -> Tensor:
        """Decode a channels-last latent to a normalized BCHW RGB image."""
        vae = _require(self._vae, "VAE")
        value = latent.unsqueeze(0).div(VAE_SCALING_FACTOR).permute(0, 4, 1, 2, 3).squeeze(2)
        tile = (self.config.vae_spatial_tile_size, self.config.vae_spatial_tile_size)
        overlap = (self.config.vae_spatial_tile_overlap, self.config.vae_spatial_tile_overlap)
        return vae.decode(
            value,
            tiled=self.config.vae_spatial_tiling,
            tile_size=tile,
            tile_overlap=overlap,
        ).sample

    def _ensure_loaded(self) -> None:
        """Download assets and materialize both models on first inference."""
        if self._dit is not None:
            return
        dit_path = self.config.dit_path or _download(
            MODEL_REPOSITORY,
            DIT_FILENAME,
            self.config.cache_dir,
            self.download_progress,
            revision=MODEL_REVISION,
        )
        vae_path = self.config.vae_path or _download(
            MODEL_REPOSITORY,
            VAE_FILENAME,
            self.config.cache_dir,
            self.download_progress,
            revision=MODEL_REVISION,
        )
        positive_path = self.config.positive_embedding_path or _download(
            EMBEDDING_REPOSITORY,
            POSITIVE_EMBEDDING_FILENAME,
            self.config.cache_dir,
            self.download_progress,
            revision=EMBEDDING_REVISION,
        )
        self._positive_embedding = _load_embedding(positive_path, self.device, self.compute_dtype)
        self._vae = _load_model(
            _new_vae,
            vae_path,
            self.device,
            state_dtype=self.compute_dtype,
        )
        self._dit = _load_model(
            _new_dit,
            dit_path,
            self.device,
            state_dtype=self.compute_dtype if self.device.type == "cpu" else None,
        )
        for module in self._dit.modules():
            if type(module).__name__ == "FlashAttentionVarlen":
                attention = cast("_AttentionModule", module)
                attention.attention_mode = "sdpa"
                attention.compute_dtype = self.compute_dtype


def _new_dit() -> NaDiT:
    """Create the exact 3B architecture described by numz's 3B config."""
    layer_count = 32
    return NaDiT(
        vid_in_channels=33,
        vid_out_channels=16,
        vid_dim=2560,
        vid_out_norm="fusedrms",
        txt_in_dim=5120,
        txt_in_norm="fusedln",
        txt_dim=2560,
        emb_dim=15360,
        heads=20,
        head_dim=128,
        expand_ratio=4,
        norm="fusedrms",
        norm_eps=1e-5,
        ada="single",
        qk_bias=False,
        qk_norm="fusedrms",
        patch_size=(1, 2, 2),
        num_layers=layer_count,
        mm_layers=10,
        mlp_type="swiglu",
        block_type=("mmdit_sr",) * layer_count,
        window=((4, 3, 3),) * layer_count,
        window_method=tuple(
            method
            for _ in range(layer_count // 2)
            for method in ("720pwin_by_size_bysize", "720pswin_by_size_bysize")
        ),
        rope_type="mmrope3d",
        rope_dim=128,
        attention_mode="sdpa",
    )


def _new_vae() -> VideoAutoencoderKLWrapper:
    """Create the VAE architecture paired with official SeedVR2 checkpoints."""
    model = VideoAutoencoderKLWrapper(
        act_fn="silu",
        block_out_channels=(128, 256, 512, 512),
        down_block_types=("DownEncoderBlock3D",) * 4,
        up_block_types=("UpDecoderBlock3D",) * 4,
        in_channels=3,
        out_channels=3,
        latent_channels=16,
        layers_per_block=2,
        norm_num_groups=32,
        temporal_scale_num=2,
        inflation_mode="pad",
        use_quant_conv=False,
        use_post_quant_conv=False,
        slicing_sample_min_size=4,
        spatial_downsample_factor=8,
        temporal_downsample_factor=4,
        freeze_encoder=False,
        gradient_checkpoint=True,
    )
    # The upstream ComfyUI host normally attaches this optional logger. Its
    # VAE spatial-tiling branch accesses the attribute directly, so standalone
    # inference must explicitly disable the absent host hook.
    model.debug = None
    return model


def _load_model[ModelT: torch.nn.Module](
    factory: Callable[[], ModelT],
    path: Path,
    device: torch.device,
    *,
    state_dtype: torch.dtype | None = None,
) -> ModelT:
    """Build on meta and assign SafeTensors without a duplicate initialized model."""
    with torch.device("meta"):
        model = factory()
    state = load_file(str(path), device=str(device))
    if state_dtype is not None:
        state = {
            name: value.to(state_dtype) if value.is_floating_point() else value
            for name, value in state.items()
        }
    incompatible = model.load_state_dict(state, strict=False, assign=True)
    if incompatible.missing_keys or incompatible.unexpected_keys:
        msg = (
            f"checkpoint does not match {type(model).__name__}: "
            f"missing={incompatible.missing_keys[:5]}, "
            f"unexpected={incompatible.unexpected_keys[:5]}"
        )
        raise RuntimeError(msg)
    del state
    _materialize_meta_buffers(model, device)
    model.eval().requires_grad_(requires_grad=False)
    gc.collect()
    return model


def _materialize_meta_buffers(model: nn.Module, device: torch.device) -> None:
    """Replace rare non-checkpoint meta buffers before moving the model."""
    for name, buffer in tuple(model.named_buffers()):
        if buffer.device.type != "meta":
            continue
        module: nn.Module = model
        parts = name.split(".")
        for part in parts[:-1]:
            module = getattr(module, part)
        module.register_buffer(parts[-1], torch.zeros_like(buffer, device=device), persistent=False)


def _load_embedding(path: Path, device: torch.device, dtype: torch.dtype) -> Tensor:
    """Load a trusted official fixed prompt embedding."""
    value = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(value, torch.Tensor):
        msg = f"expected a tensor in {path}"
        raise TypeError(msg)
    return value.to(device=device, dtype=dtype)


def _download(
    repository: str,
    filename: str,
    cache_dir: Path | None,
    progress: DownloadProgress | None,
    *,
    revision: str,
) -> Path:
    """Resolve one immutable Hugging Face asset, reusing its versioned cache."""
    previous_verbosity = hugging_face_logging.get_verbosity()
    hugging_face_logging.set_verbosity_error()
    try:
        result = hf_hub_download(
            repo_id=repository,
            filename=filename,
            revision=revision,
            cache_dir=str(cache_dir) if cache_dir is not None else None,
            tqdm_class=hugging_face_progress_class(progress) if progress is not None else None,
        )
    finally:
        hugging_face_logging.set_verbosity(previous_verbosity)
    return Path(result)


def _resolve_device(value: str) -> torch.device:
    """Resolve ``auto`` and validate the requested accelerator."""
    if value == "auto":
        if torch.cuda.is_available():
            return torch.device("cuda", torch.cuda.current_device())
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")
    device = torch.device(value)
    if device.type == "cuda" and not torch.cuda.is_available():
        msg = f"CUDA device requested but CUDA is unavailable: {value}"
        raise ValueError(msg)
    return device


def _compute_dtype(device: torch.device) -> torch.dtype:
    """Match numz's BF16 probe, with FP32 retained for CPU correctness."""
    if device.type == "cpu":
        return torch.float32
    if device.type == "mps":
        return torch.float16
    try:
        probe = torch.randn((8, 8), dtype=torch.bfloat16, device=device)
        torch.matmul(probe, probe)
    except RuntimeError as exc:
        if "not supported" in str(exc).casefold():
            return torch.float16
        raise
    return torch.bfloat16


def _like(tensor: Tensor) -> dict[str, Any]:
    """Return common tensor-construction keyword arguments."""
    return {"device": tensor.device, "dtype": tensor.dtype}


def _edge_antialias(image: np.ndarray, strength: float) -> np.ndarray:
    """Port numz's wrapper-level Sobel-guided smoothing without SciPy.

    Flat regions receive a small Gaussian blend while strong edges keep the
    generated pixels. Numz's current wrapper uses strength 0.2 and sigma 0.8.
    """
    source = image.astype(np.float64)
    result = np.empty_like(source)
    sigma = 0.5 + strength * 1.5
    radius = int(4.0 * sigma + 0.5)
    positions = np.arange(-radius, radius + 1, dtype=np.float64)
    gaussian = np.exp(-0.5 * (positions / sigma) ** 2)
    gaussian /= gaussian.sum()
    for channel in range(RGB_CHANNELS):
        values = source[:, :, channel]
        padded = np.pad(values, 1, mode="symmetric")
        sobel_x = (
            padded[:-2, 2:]
            + 2.0 * padded[1:-1, 2:]
            + padded[2:, 2:]
            - padded[:-2, :-2]
            - 2.0 * padded[1:-1, :-2]
            - padded[2:, :-2]
        )
        sobel_y = (
            padded[2:, :-2]
            + 2.0 * padded[2:, 1:-1]
            + padded[2:, 2:]
            - padded[:-2, :-2]
            - 2.0 * padded[:-2, 1:-1]
            - padded[:-2, 2:]
        )
        edge = np.sqrt(sobel_x**2 + sobel_y**2)
        maximum = edge.max()
        if maximum > 0:
            edge /= maximum
        smoothed = _separable_filter(values, gaussian)
        smooth_fraction = (1.0 - edge) * strength
        result[:, :, channel] = values * (1.0 - smooth_fraction) + smoothed * smooth_fraction
    return np.clip(result, 0, 255).astype(np.uint8)


def _separable_filter(image: np.ndarray, kernel: np.ndarray) -> np.ndarray:
    """Apply a small symmetric-boundary Gaussian kernel along both axes."""
    radius = len(kernel) // 2
    horizontal_pad = np.pad(image, ((0, 0), (radius, radius)), mode="symmetric")
    horizontal = sum(
        weight * horizontal_pad[:, offset : offset + image.shape[1]]
        for offset, weight in enumerate(kernel)
    )
    vertical_pad = np.pad(horizontal, ((radius, radius), (0, 0)), mode="symmetric")
    return sum(
        weight * vertical_pad[offset : offset + image.shape[0], :]
        for offset, weight in enumerate(kernel)
    )


def _require[ValueT](value: ValueT | None, name: str) -> ValueT:
    """Narrow an attribute after lazy loading or fail with an internal error."""
    if value is None:
        msg = f"SeedVR2 {name} was not loaded"
        raise RuntimeError(msg)
    return value
