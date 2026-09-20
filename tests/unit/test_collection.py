"""Default, slow and platform selection work before unsupported imports run."""

from pathlib import Path

import pytest


@pytest.mark.parametrize("platform", ["linux", "win32"])
@pytest.mark.parametrize("slow", [False, True])
def test_selection_keeps_game_tests_opt_in(
    pytester: pytest.Pytester, platform: str, *, slow: bool
) -> None:
    hooks = (Path(__file__).parents[1] / "conftest.py").read_text(encoding="utf-8")
    # Simulate only our platform selection, not Python or any library's platform.
    pytester.makeconftest(hooks.replace("sys.platform", repr(platform)))
    pytester.makeini("[pytest]\nmarkers =\n    slow\n    windows\n    visual\n")
    pytester.makepyfile(
        """
        import pytest

        def test_portable():
            pass

        @pytest.mark.slow
        def test_slow():
            pass

        @pytest.mark.windows
        def test_windows_marker():
            pass

        @pytest.mark.visual
        def test_live_game():
            raise AssertionError("must never launch implicitly")
        """
    )
    windows = pytester.path / "windows"
    windows.mkdir()
    (windows / "test_api.py").write_text(
        "def test_windows_api(): pass\n"
        if platform == "win32"
        else "raise RuntimeError('Windows module must not even be imported')\n",
        encoding="utf-8",
    )
    result = pytester.runpytest("--strict-markers", *(["--slow"] if slow else []))
    result.assert_outcomes(
        passed=1 + int(slow) + (2 if platform == "win32" else 0),
        skipped=1 if platform == "win32" else 2,
        deselected=0 if slow else 1,
    )
