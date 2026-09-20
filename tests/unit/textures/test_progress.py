"""Tests for optional-backend progress adaptation."""

from gk3hd.textures.progress import hugging_face_progress_class


def test_hugging_face_progress_is_forwarded_without_tqdm_output() -> None:
    """The Hub-compatible bridge reports initial and incremental byte counts."""
    updates: list[tuple[str, int, int | None]] = []
    progress_class = hugging_face_progress_class(
        lambda name, completed, total: updates.append((name, completed, total))
    )

    with progress_class(desc="weights.safetensors", total=10, initial=2) as progress:
        progress.update(3)
        progress.update(5)

    assert updates == [
        ("weights.safetensors", 2, 10),
        ("weights.safetensors", 5, 10),
        ("weights.safetensors", 10, 10),
    ]
    assert progress.closed
