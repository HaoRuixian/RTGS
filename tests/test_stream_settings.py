from core.global_config import GlobalConfig
from core.stream_settings import is_realtime_stream_configured


def test_global_config_preserves_independent_ephemeris_and_ssr_streams():
    config = GlobalConfig()
    config.update_settings(
        "EPH",
        {
            "enabled": True,
            "source_type": "NTRIP Server",
            "host": "caster.example.com",
            "port": "2101",
            "mountpoint": "BRDC",
        },
    )
    config.update_settings(
        "SSR",
        {
            "enabled": True,
            "source_type": "NTRIP Server",
            "host": "caster.example.com",
            "port": "2101",
            "mountpoint": "SSRA",
        },
    )

    payload = config.to_dict()

    assert payload["eph_settings"]["mountpoint"] == "BRDC"
    assert payload["ssr_settings"]["mountpoint"] == "SSRA"

    restored = GlobalConfig()
    restored.from_dict(payload)

    assert restored.eph_settings.mountpoint == "BRDC"
    assert restored.ssr_settings.mountpoint == "SSRA"
    assert restored.get_connection_settings("SSR").enabled is True


def test_realtime_stream_configuration_supports_separate_mountpoints():
    eph_settings = {
        "source": "NTRIP Server",
        "host": "caster.example.com",
        "port": "2101",
        "mountpoint": "BRDC",
    }
    ssr_settings = {
        "source": "NTRIP Server",
        "host": "caster.example.com",
        "port": "2101",
        "mountpoint": "SSRA",
    }

    assert is_realtime_stream_configured(eph_settings)
    assert is_realtime_stream_configured(ssr_settings)
    assert eph_settings["mountpoint"] != ssr_settings["mountpoint"]
