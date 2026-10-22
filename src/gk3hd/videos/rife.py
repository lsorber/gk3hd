"""Lazy RIFE 4.25 inference using existing upscale dependencies only."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import torch
from PIL import Image
from torch.nn import functional

from gk3hd.system.download import download_verified
from gk3hd.system.files import cache_directory
from gk3hd.system.locking import ExclusiveFileLock
from gk3hd.videos._vendor.rife.model import IFNet

if TYPE_CHECKING:
    from gk3hd.textures.progress import DownloadProgress

WEIGHTS_URL = "https://github.com/HolyWu/vs-rife/releases/download/model/flownet_v4.25.pkl"
WEIGHTS_SHA256 = "6615790efd627772917205db291f51cd392528a157ecbb2ecaeec3bff8eb6de2"
WEIGHTS_SIZE = 24636301
_FULL_HD_PIXELS = 1920 * 1080


class RifeInterpolator:
    """Keep only the model and one anchor pair on the requested inference device."""

    def __init__(
        self, device: str = "auto", *, download_progress: DownloadProgress | None = None
    ) -> None:
        """Defer downloads and allocation until a non-static pair needs interpolation."""
        self.device = (
            torch.device("cuda" if torch.cuda.is_available() else "cpu")
            if device == "auto"
            else torch.device(device)
        )
        self.download_progress = download_progress
        self.model = None
        self._anchors: tuple[Image.Image, Image.Image] | None = None
        self._inputs: tuple[torch.Tensor, ...] = ()

    def _load(self) -> IFNet:
        if self.model is None:
            path = cache_directory() / "rife" / WEIGHTS_SHA256 / "flownet.pkl"
            progress = self.download_progress
            with ExclusiveFileLock(path.with_suffix(".lock")):
                download_verified(
                    WEIGHTS_URL,
                    path,
                    sha256=WEIGHTS_SHA256,
                    size=WEIGHTS_SIZE,
                    progress=(lambda done, total: progress("RIFE 4.25", done, total))
                    if progress is not None
                    else None,
                )
            weights = torch.load(path, map_location="cpu", weights_only=True)
            model = IFNet()
            # Training-only teacher/timing heads are not part of inference.
            model.load_state_dict({key: weights[f"module.{key}"] for key in model.state_dict()})
            self.model = model.eval().to(self.device)
        return self.model

    @torch.inference_mode()
    def interpolate(self, left: Image.Image, right: Image.Image, time: float) -> Image.Image:
        """Infer arbitrary quarter frames in float32, without changing anchors."""
        if left.size != right.size or not 0 < time < 1:
            msg = "interpolation requires matching frame dimensions and a time between 0 and 1"
            raise ValueError(msg)
        model = self._load()
        if self._anchors is None or left is not self._anchors[0] or right is not self._anchors[1]:
            self._prepare(left, right, model)
        first, second, divisor, grid, feature0, feature1 = self._inputs
        timestep = torch.full_like(first[:, :1], time)
        result = model(first, second, timestep, divisor, grid, feature0, feature1)
        pixels = result[0, :, : left.height, : left.width].permute(1, 2, 0)
        return Image.fromarray(pixels.clamp(0, 1).mul(255).round().byte().cpu().numpy())

    def _prepare(self, left: Image.Image, right: Image.Image, model: IFNet) -> None:
        scale = 0.5 if left.width * left.height > _FULL_HD_PIXELS else 1.0
        model.scale_list = [16 / scale, 8 / scale, 4 / scale, 2 / scale, 1 / scale]
        modulo = int(64 / scale)
        width = (left.width + modulo - 1) // modulo * modulo
        height = (left.height + modulo - 1) // modulo * modulo
        tensors = []
        for image in (left, right):
            tensor = torch.from_numpy(np.array(image.convert("RGB"))).permute(2, 0, 1)
            tensor = tensor.unsqueeze(0).to(self.device, torch.float32).div(255)
            tensors.append(functional.pad(tensor, (0, width - left.width, 0, height - left.height)))
        horizontal = torch.linspace(-1, 1, width, device=self.device).view(1, 1, 1, width)
        vertical = torch.linspace(-1, 1, height, device=self.device).view(1, 1, height, 1)
        grid = torch.cat(
            (horizontal.expand(1, 1, height, width), vertical.expand(1, 1, height, width)), 1
        )
        divisor = torch.tensor(((width - 1) / 2, (height - 1) / 2), device=self.device)
        self._inputs = (*tensors, divisor, grid, model.encode(tensors[0]), model.encode(tensors[1]))
        self._anchors = (left, right)
