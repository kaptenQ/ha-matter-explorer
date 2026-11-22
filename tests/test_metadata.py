from custom_components.matter_explorer.metadata import (
    BITMAP,
    BOOL,
    ENUM,
    INT,
    LIST,
    STRING,
    display_value,
    get_path_meta,
    is_readonly_cluster,
)


def test_keypad_lockout_enum() -> None:
    meta = get_path_meta("1/516/1")
    assert meta.cluster_name == "ThermostatUserInterfaceConfiguration"
    assert meta.attribute_name == "KeypadLockout"
    assert meta.type == ENUM
    assert sorted(meta.enum_values) == [0, 1, 2, 3, 4, 5]
    assert meta.enum_values[0] == "NoLockout"
    assert not meta.unknown_cluster
    assert display_value(meta, 1) == "Level 1"
    assert meta.enum_values[1] == "Lockout1"  # the spec name stays (panel tooltip)
    assert meta.as_dict()["enum_labels"]["0"] == "Off"


def test_local_temperature() -> None:
    meta = get_path_meta("1/513/0")
    assert meta.cluster_name == "Thermostat"
    assert meta.attribute_name == "LocalTemperature"
    assert meta.type == INT
    assert meta.nullable
    assert display_value(meta, 1950) == 19.5
    assert display_value(meta, None) is None


def test_other_types() -> None:
    assert get_path_meta("0/40/5").type == STRING
    assert get_path_meta("1/6/0").type == BOOL
    assert get_path_meta("1/513/65532").type == BITMAP
    assert get_path_meta("1/513/65531").type == LIST
    assert get_path_meta("1/513/72").type == LIST  # Presets
    assert get_path_meta("1/513/27").type == ENUM  # ControlSequenceOfOperation


def test_unknown_cluster() -> None:
    # 293403649 is IKEA's manufacturer cluster (vendor 0x117C, id 0xFC01)
    meta = get_path_meta("1/293403649/0")
    assert meta.unknown_cluster
    assert meta.cluster_name == "0x117CFC01"
    assert meta.attribute_name == "0x0000"
    assert is_readonly_cluster(293403649)
    # the id written in the spec text
    assert get_path_meta(f"1/{0x117C0001}/1").cluster_name == "0x117C0001"
    assert is_readonly_cluster(0x117C0001)
    assert not is_readonly_cluster(516)


def test_friendly_labels_cover_known_enums() -> None:
    from custom_components.matter_explorer.metadata import FRIENDLY_LABELS
    from custom_components.matter_explorer.writable import WRITABLE

    assert display_value(get_path_meta("1/516/0"), 1) == "Fahrenheit"
    assert display_value(get_path_meta("1/513/28"), 4) == "Heat"
    assert display_value(get_path_meta("1/513/28"), 5) == "Emergency heat"
    for key, labels in FRIENDLY_LABELS.items():  # every writable value has a friendly label
        assert set(WRITABLE[key].values) == set(labels)
