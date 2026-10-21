from pathlib import Path

import pytest

from inkcast.config import Config, DeviceConfig, load_config


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_defaults_when_file_only_sets_default_url(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, 'default_url = "http://mm:8080"\n'))

    assert config == Config(default_url="http://mm:8080")
    assert config.host == "0.0.0.0"
    assert config.port == 11113
    assert config.refresh_seconds == 300


def test_default_url_is_the_device_page_when_not_set(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, "port = 11113\n"))

    assert config.default_url == "about:device"
    assert config.device("abcdef00-1111-2222-3333-444455556666").url == "about:device"


def test_device_overrides_are_parsed_and_uuid_normalised(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path,
            """
default_url = "http://mm:8080"

[devices."ABCDEF00-1111-2222-3333-444455556666"]
url = "http://other/"
rotate = 180
sleep_minutes = 10
fit = "cover"
touch = true
""",
        )
    )

    device = config.device("abcdef00-1111-2222-3333-444455556666")
    assert device == DeviceConfig(
        url="http://other/", rotate=180, sleep_minutes=10, fit="cover", touch=True
    )


def test_unknown_device_falls_back_to_default_url(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, 'default_url = "http://mm:8080"\n'))

    assert config.device("00000000-0000-0000-0000-000000000000") == DeviceConfig(
        url="http://mm:8080"
    )


def test_invalid_rotation_is_rejected(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
default_url = "http://mm:8080"
[devices."00000000-0000-0000-0000-000000000000"]
rotate = 45
""",
    )

    with pytest.raises(ValueError, match="rotate must be one of 0, 90, 180, 270"):
        load_config(path)


def test_fit_defaults_to_contain(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, 'default_url = "http://mm:8080"\n'))

    assert config.device("00000000-0000-0000-0000-000000000000").fit == "contain"


def test_touch_defaults_to_off(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, 'default_url = "http://mm:8080"\n'))

    assert config.device("00000000-0000-0000-0000-000000000000").touch is False


def test_invalid_fit_is_rejected(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
default_url = "http://mm:8080"
[devices."00000000-0000-0000-0000-000000000000"]
fit = "zoom"
""",
    )

    with pytest.raises(ValueError, match="fit must be one of contain, cover, stretch"):
        load_config(path)


def test_device_refresh_seconds_overrides_the_global_one(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path,
            """
default_url = "http://mm:8080"
refresh_seconds = 3600

[devices."00000000-0000-0000-0000-000000000001"]
refresh_seconds = 60
""",
        )
    )

    assert config.refresh_seconds_for("00000000-0000-0000-0000-000000000001") == 60


def test_devices_without_refresh_seconds_use_the_global_one(tmp_path: Path) -> None:
    config = load_config(
        write(
            tmp_path,
            """
default_url = "http://mm:8080"
refresh_seconds = 3600

[devices."00000000-0000-0000-0000-000000000001"]
url = "http://other/"
""",
        )
    )

    assert config.refresh_seconds_for("00000000-0000-0000-0000-000000000001") == 3600
    assert config.refresh_seconds_for("00000000-0000-0000-0000-000000000002") == 3600
