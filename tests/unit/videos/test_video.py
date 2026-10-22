from fractions import Fraction
from pathlib import Path

import av
import numpy as np
from PIL import Image


def _make_movie(path: Path, *, audio: bool, rate: Fraction = Fraction(30000, 1001)) -> None:
    with av.open(str(path), "w") as container:
        video = container.add_stream("mjpeg", rate=rate)
        video.width, video.height, video.pix_fmt = 16, 12, "yuvj444p"
        sound = container.add_stream("pcm_s16le", rate=8000) if audio else None
        if sound is not None:
            sound.layout = "mono"
        for index in range(7):
            frame = av.VideoFrame.from_image(Image.new("RGB", (16, 12), (index * 30, 60, 90)))
            frame.pts, frame.time_base = index, 1 / rate
            container.mux(video.encode(frame))
            if sound is not None:
                samples = np.arange(267, dtype=np.int16)[None, :]
                sample = av.AudioFrame.from_ndarray(samples, format="s16", layout="mono")
                sample.sample_rate = 8000
                sample.pts, sample.time_base = index * 267, Fraction(1, 8000)
                container.mux(sound.encode(sample))
        container.mux(video.encode(None))
        if sound is not None:
            container.mux(sound.encode(None))
