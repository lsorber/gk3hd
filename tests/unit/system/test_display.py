"""Physical display-mode selection for KDE Wayland and Gamescope/X11."""

import json

from gk3hd.system.display import DisplayMode, _kscreen_mode, _xrandr_mode


def test_xrandr_selects_primary_output_not_combined_desktop() -> None:
    output = """Screen 0: minimum 16 x 16, current 5120 x 1440, maximum 32767 x 32767
DP-1 connected 2560x1440+0+0 (normal left inverted right)
   2560x1440     59.95*+
DP-2 connected primary 2560x1440+2560+0 (normal left inverted right)
   2560x1440    143.98*+ 59.95
"""
    assert _xrandr_mode(output) == DisplayMode(2560, 1440, 144)


def test_gamescope_deck_mode() -> None:
    assert _xrandr_mode(
        "XWAYLAND0 connected 1280x800+0+0\n   1280x800    90.00*+\n"
    ) == DisplayMode(1280, 800, 90)


def test_virtual_display_keeps_resolution_with_unknown_refresh_rate() -> None:
    assert _xrandr_mode("screen connected 1280x800+0+0\n   1280x800    0.00*\n") == DisplayMode(
        1280, 800, 60
    )


def test_kde_uses_physical_mode_not_scaled_size_and_respects_rotation() -> None:
    payload = {
        "outputs": [
            {
                "enabled": True,
                "connected": True,
                "priority": 1,
                "currentModeId": "deck",
                "rotation": 2,
                "scale": 1.5,
                "size": {"width": 853, "height": 533},
                "modes": [
                    {"id": "deck", "size": {"width": 800, "height": 1280}, "refreshRate": 90.0}
                ],
            }
        ]
    }
    assert _kscreen_mode(json.dumps(payload)) == DisplayMode(1280, 800, 90)


def test_steam_deck_portrait_panel_reports_rotated_landscape_mode() -> None:
    # The Deck panel's actual mode is portrait (800x1280); KScreen reports
    # rotation 8 and a landscape screen. Keep the relevant fields from a real
    # SteamOS KScreen dump, including its disabled external output:
    # https://gist.github.com/parkerlreed/682067530145260f0035b032203f26b8
    payload = {
        "outputs": [
            {
                "connected": True,
                "enabled": True,
                "currentModeId": "85",
                "primary": True,
                "rotation": 8,
                "modes": [
                    {"id": "85", "size": {"width": 800, "height": 1280}, "refreshRate": 59.9985}
                ],
            },
            {
                "connected": False,
                "enabled": False,
                "currentModeId": "",
                "primary": False,
                "rotation": 1,
                "modes": [],
            },
        ]
    }
    assert _kscreen_mode(json.dumps(payload)) == DisplayMode(1280, 800, 60)


def test_kde_flipped_quarter_turns_exchange_display_axes() -> None:
    for rotation in (32, 128):
        payload = {
            "outputs": [
                {
                    "connected": True,
                    "enabled": True,
                    "currentModeId": "1",
                    "rotation": rotation,
                    "modes": [
                        {"id": "1", "size": {"width": 800, "height": 1280}, "refreshRate": 90}
                    ],
                }
            ]
        }
        assert _kscreen_mode(json.dumps(payload)) == DisplayMode(1280, 800, 90)


def test_no_display_or_malformed_output_returns_none() -> None:
    assert _kscreen_mode("not JSON") is None
    assert _kscreen_mode("{}") is None
    assert _xrandr_mode("DP-1 disconnected\n") is None
