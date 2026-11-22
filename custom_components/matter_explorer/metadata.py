"""Cluster/attribute metadata from the CHIP cluster objects shipped with matter-python-client.

``chip.clusters.Objects`` gives names, enums and bitmaps. It has no min/max, so
``min``/``max`` stay ``None`` here; the nodes command fills them from the node's
own limit attributes where the spec defines them.
"""

from __future__ import annotations

import enum
import types
import typing
from dataclasses import dataclass, field, is_dataclass
from typing import Any

from chip.clusters import ClusterObjects as CO  # noqa: N817
from chip.clusters import Objects as _objects  # noqa: F401, N813  (registers all standard clusters)
from chip.clusters import Types as ChipTypes

# Attribute types
BOOL = "bool"
ENUM = "enum"
BITMAP = "bitmap"
INT = "int"
FLOAT = "float"
STRING = "string"
BYTES = "bytes"
LIST = "list"
STRUCT = "struct"
UNKNOWN = "unknown"

FEATURE_MAP = 65532

GLOBAL_ATTRIBUTES = {
    65528: "GeneratedCommandList",
    65529: "AcceptedCommandList",
    65530: "EventList",
    65531: "AttributeList",
    65532: "FeatureMap",
    65533: "ClusterRevision",
}

# Attributes holding a temperature in 0.01 °C: (cluster id, attribute id)
CENTI_CELSIUS: frozenset[tuple[int, int]] = frozenset(
    {
        (513, 0),  # Thermostat LocalTemperature
        (513, 1),  # OutdoorTemperature
        (513, 3),  # AbsMinHeatSetpointLimit
        (513, 4),  # AbsMaxHeatSetpointLimit
        (513, 5),  # AbsMinCoolSetpointLimit
        (513, 6),  # AbsMaxCoolSetpointLimit
        (513, 17),  # OccupiedCoolingSetpoint
        (513, 18),  # OccupiedHeatingSetpoint
        (513, 19),  # UnoccupiedCoolingSetpoint
        (513, 20),  # UnoccupiedHeatingSetpoint
        (513, 21),  # MinHeatSetpointLimit
        (513, 22),  # MaxHeatSetpointLimit
        (513, 23),  # MinCoolSetpointLimit
        (513, 24),  # MaxCoolSetpointLimit
        (1026, 0),  # TemperatureMeasurement MeasuredValue
        (1026, 1),  # MinMeasuredValue
        (1026, 2),  # MaxMeasuredValue
    }
)

# Setpoint attribute -> (min limit attribute, max limit attribute) in the same cluster
SETPOINT_LIMITS: dict[tuple[int, int], tuple[int, int]] = {
    (513, 18): (21, 22),
    (513, 20): (21, 22),
    (513, 17): (23, 24),
    (513, 19): (23, 24),
}


# Friendly labels for known enums, shared by the panel, the exports and the select entities.
# Display only: writes stay numeric, and the spec names stay in ``enum_values`` (panel tooltip).
FRIENDLY_LABELS: dict[tuple[int, int], dict[int, str]] = {
    (516, 0): {0: "Celsius", 1: "Fahrenheit"},  # TemperatureDisplayMode
    (516, 1): {0: "Off", 1: "Level 1", 2: "Level 2", 3: "Level 3", 4: "Level 4", 5: "Level 5"},
    (513, 28): {  # SystemMode
        0: "Off", 1: "Auto", 3: "Cool", 4: "Heat", 5: "Emergency heat", 6: "Precooling",
        7: "Fan only", 8: "Dry", 9: "Sleep",
    },
}  # fmt: skip


def friendly_labels(cluster_id: int, attribute_id: int) -> dict[int, str] | None:
    """Friendly enum labels of an attribute, or None."""
    return FRIENDLY_LABELS.get((cluster_id, attribute_id))


@dataclass
class AttributeMeta:
    """What we know about one attribute path."""

    cluster_id: int
    attribute_id: int
    cluster_name: str
    attribute_name: str
    type: str = UNKNOWN
    nullable: bool = False
    enum_values: dict[int, str] | None = None
    bitmap_flags: dict[str, int] | None = None
    min: int | None = None
    max: int | None = None
    unknown_cluster: bool = False
    unknown_attribute: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Serialise for the websocket API."""
        out: dict[str, Any] = {
            "cluster_name": self.cluster_name,
            "attribute_name": self.attribute_name,
            "type": self.type,
            "nullable": self.nullable,
            "unknown_cluster": self.unknown_cluster,
            "unknown_attribute": self.unknown_attribute,
            "min": self.min,
            "max": self.max,
        }
        if self.enum_values is not None:
            out["enum_values"] = {str(k): v for k, v in self.enum_values.items()}
            labels = friendly_labels(self.cluster_id, self.attribute_id)
            if labels:
                out["enum_labels"] = {str(k): v for k, v in labels.items()}
        if self.bitmap_flags is not None:
            out["bitmap_flags"] = self.bitmap_flags
        return out


def parse_path(path: str) -> tuple[int, int, int]:
    """Split "endpoint/cluster/attribute" into three ints."""
    endpoint, cluster, attribute = path.split("/")
    return int(endpoint), int(cluster), int(attribute)


def hex_name(value: int) -> str:
    """Name for an unknown id, e.g. 0x117CFC01."""
    return f"0x{value:08X}" if value > 0xFFFF else f"0x{value:04X}"


def enum_label(name: str) -> str:
    """kLockout1 -> Lockout1."""
    return name[1:] if len(name) > 1 and name[0] == "k" and name[1].isupper() else name


def _strip_optional(tp: Any) -> tuple[Any, bool]:
    """Remove None / Nullable from a (union) type; return (type, nullable)."""
    nullable = False
    origin = typing.get_origin(tp)
    if origin in (typing.Union, types.UnionType):
        rest = []
        for arg in typing.get_args(tp):
            if arg is type(None):
                continue
            if arg is ChipTypes.Nullable:
                nullable = True
                continue
            rest.append(arg)
        if len(rest) == 1:
            return rest[0], nullable
        if rest:
            return rest[0], nullable
    return tp, nullable


def _classify(tp: Any) -> tuple[str, dict[str, Any]]:
    """Map a python/CHIP type to our type names plus details."""
    if tp is bool:
        return BOOL, {}
    if isinstance(tp, type):
        if issubclass(tp, enum.IntFlag):
            flags = {m.name: int(m.value) for m in tp if m.name}
            return BITMAP, {"bitmap_flags": flags}
        if issubclass(tp, enum.Enum):
            values = {int(m.value): enum_label(m.name) for m in tp if m.name != "kUnknownEnumValue"}
            return ENUM, {"enum_values": values}
        if issubclass(tp, bool):
            return BOOL, {}
        if issubclass(tp, float):
            return FLOAT, {}
        if issubclass(tp, int):
            return INT, {}
        if issubclass(tp, str):
            return STRING, {}
        if issubclass(tp, (bytes, bytearray)):
            return BYTES, {}
        if is_dataclass(tp):
            return STRUCT, {}
    if typing.get_origin(tp) in (list, typing.List):  # noqa: UP006
        return LIST, {}
    return UNKNOWN, {}


def get_attribute_meta(cluster_id: int, attribute_id: int) -> AttributeMeta:
    """Metadata for a cluster/attribute id pair (never raises)."""
    unknown_cluster = is_readonly_cluster(cluster_id)
    # Manufacturer clusters (vendor prefix in the id) are unknown to us even when
    # matter_server registers a custom cluster class for them (IKEA's, Eve's, ...).
    cluster_cls = None if unknown_cluster else CO.ALL_CLUSTERS.get(cluster_id)
    cluster_name = (
        hex_name(cluster_id) if unknown_cluster or cluster_cls is None else cluster_cls.__name__
    )
    attr_cls = None if unknown_cluster else CO.ALL_ATTRIBUTES.get(cluster_id, {}).get(attribute_id)

    if attr_cls is None:
        name = GLOBAL_ATTRIBUTES.get(attribute_id)
        meta = AttributeMeta(
            cluster_id,
            attribute_id,
            cluster_name,
            name or hex_name(attribute_id),
            unknown_cluster=unknown_cluster,
            unknown_attribute=name is None,
        )
        if name == "FeatureMap":
            meta.type = BITMAP
        elif name in ("ClusterRevision",):
            meta.type = INT
        elif name:
            meta.type = LIST
        return meta

    tp, nullable = _strip_optional(attr_cls.attribute_type.Type)
    kind, details = _classify(tp)
    if attribute_id == FEATURE_MAP:
        kind = BITMAP
        feature = getattr(getattr(cluster_cls, "Bitmaps", None), "Feature", None)
        if feature is not None:
            details = {"bitmap_flags": {m.name: int(m.value) for m in feature if m.name}}
    return AttributeMeta(
        cluster_id,
        attribute_id,
        cluster_name,
        attr_cls.__name__,
        type=kind,
        nullable=nullable,
        unknown_cluster=unknown_cluster,
        enum_values=details.get("enum_values"),
        bitmap_flags=details.get("bitmap_flags"),
    )


def get_path_meta(path: str) -> AttributeMeta:
    """Metadata for an "endpoint/cluster/attribute" path."""
    _, cluster_id, attribute_id = parse_path(path)
    return get_attribute_meta(cluster_id, attribute_id)


def is_readonly_cluster(cluster_id: int) -> bool:
    """Unknown clusters (manufacturer-specific or not in the CHIP objects) are read-only."""
    return cluster_id > 0xFFFF or cluster_id not in CO.ALL_CLUSTERS


def display_value(meta: AttributeMeta, value: Any) -> Any:
    """Human friendly value: enum label, °C for 0.01 °C temperatures, else None."""
    if value is None or isinstance(value, bool):
        return None
    if meta.type == ENUM and isinstance(value, int) and meta.enum_values:
        labels = friendly_labels(meta.cluster_id, meta.attribute_id) or {}
        return labels.get(value, meta.enum_values.get(value))
    if (meta.cluster_id, meta.attribute_id) in CENTI_CELSIUS and isinstance(value, int | float):
        return round(value / 100, 2)
    return None
