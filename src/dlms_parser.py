import logging
from dataclasses import dataclass
from typing import Any, Optional

log = logging.getLogger(__name__)


class FrameParseError(Exception):
    pass


@dataclass(frozen=True)
class ObisEntry:
    key: str
    name: str
    unit: Optional[str]
    ha_domain: str
    ha_device_class: Optional[str]
    ha_state_class: Optional[str]
    ha_entity_category: Optional[str] = None


@dataclass
class ParsedValue:
    obis: tuple
    class_id: int
    attribute: int
    raw_value: Any
    entry: ObisEntry


@dataclass
class ParseResult:
    invoke_id: int
    notification_type: int
    values: dict  # str -> ParsedValue


# DLMS data type tags as used by this meter
_DTYPE_NULL = 0x00
_DTYPE_DOUBLE_LONG_UNSIGNED = 0x06  # uint32 big-endian
_DTYPE_OCTET_STRING = 0x09          # length-prefixed bytes
_DTYPE_ENUM = 0x16                   # uint8 enum value (used for relays, disconnect, notification type)
_DTYPE_ENUM_ALT = 0x26              # alternate enum tag seen in sample data (treated identically)
_DTYPE_VENDOR_WRAP = 0x62           # vendor-specific wrapper; parse following value recursively


# Map raw enum integers to human-readable strings for binary_sensor fields.
# Per IEC 62056-62: 0=disconnected, 1=connected, 2=ready_for_reconnection
_ENUM_STATUS = {0: "disconnected", 1: "connected", 2: "disconnected"}


def _e(key, name, unit, domain, dc, sc, cat=None):
    return ObisEntry(key, name, unit, domain, dc, sc, cat)


# Registry keyed by OBIS 6-tuple (A, B, C, D, E, F)
OBIS_REGISTRY: dict[tuple, ObisEntry] = {
    (0, 0, 42, 0, 0, 255):   _e("device_name",        "COSEM Device Name",               None,  "sensor",        None,     None,               "diagnostic"),
    (0, 2, 25, 9, 0, 255):   _e("push_setup",          "Push Setup",                      None,  "sensor",        None,     None,               "diagnostic"),
    (0, 0, 96, 1, 0, 255):   _e("serial_number",       "Serial Number",                   None,  "sensor",        None,     None,               "diagnostic"),
    (0, 0, 96, 3, 10, 255):  _e("disconnect_status",   "Disconnect Status",               None,  "binary_sensor", None,     None,               None),
    (0, 0, 17, 0, 0, 255):   _e("power_limiter",       "Power Limiter",                   "W",   "sensor",        "power",  "measurement",      None),
    (0, 1, 96, 3, 10, 255):  _e("relay_1_status",      "Relay 1 Status",                  None,  "binary_sensor", None,     None,               None),
    (0, 2, 96, 3, 10, 255):  _e("relay_2_status",      "Relay 2 Status",                  None,  "binary_sensor", None,     None,               None),
    (0, 3, 96, 3, 10, 255):  _e("relay_3_status",      "Relay 3 Status",                  None,  "binary_sensor", None,     None,               None),
    (0, 4, 96, 3, 10, 255):  _e("relay_4_status",      "Relay 4 Status",                  None,  "binary_sensor", None,     None,               None),
    (0, 5, 96, 3, 10, 255):  _e("relay_5_status",      "Relay 5 Status",                  None,  "binary_sensor", None,     None,               None),
    (0, 6, 96, 3, 10, 255):  _e("relay_6_status",      "Relay 6 Status",                  None,  "binary_sensor", None,     None,               None),
    (0, 0, 96, 14, 0, 255):  _e("active_tariff",       "Active Tariff",                   None,  "sensor",        None,     None,               "diagnostic"),
    (1, 0, 1, 7, 0, 255):    _e("power_import_total",  "Active Power Import Total",       "W",   "sensor",        "power",  "measurement",      None),
    (1, 0, 21, 7, 0, 255):   _e("power_import_l1",     "Active Power Import L1",          "W",   "sensor",        "power",  "measurement",      None),
    (1, 0, 41, 7, 0, 255):   _e("power_import_l2",     "Active Power Import L2",          "W",   "sensor",        "power",  "measurement",      None),
    (1, 0, 61, 7, 0, 255):   _e("power_import_l3",     "Active Power Import L3",          "W",   "sensor",        "power",  "measurement",      None),
    (1, 0, 2, 7, 0, 255):    _e("power_export_total",  "Active Power Export Total",       "W",   "sensor",        "power",  "measurement",      None),
    (1, 0, 22, 7, 0, 255):   _e("power_export_l1",     "Active Power Export L1",          "W",   "sensor",        "power",  "measurement",      None),
    (1, 0, 42, 7, 0, 255):   _e("power_export_l2",     "Active Power Export L2",          "W",   "sensor",        "power",  "measurement",      None),
    (1, 0, 62, 7, 0, 255):   _e("power_export_l3",     "Active Power Export L3",          "W",   "sensor",        "power",  "measurement",      None),
    (1, 0, 1, 8, 0, 255):    _e("energy_import_total", "Cumulative Import Energy Total",  "Wh",  "sensor",        "energy", "total_increasing", None),
    (1, 0, 1, 8, 1, 255):    _e("energy_import_rate1", "Cumulative Import Energy Rate 1", "Wh",  "sensor",        "energy", "total_increasing", None),
    (1, 0, 1, 8, 2, 255):    _e("energy_import_rate2", "Cumulative Import Energy Rate 2", "Wh",  "sensor",        "energy", "total_increasing", None),
    (1, 0, 1, 8, 3, 255):    _e("energy_import_rate3", "Cumulative Import Energy Rate 3", "Wh",  "sensor",        "energy", "total_increasing", None),
    (1, 0, 1, 8, 4, 255):    _e("energy_import_rate4", "Cumulative Import Energy Rate 4", "Wh",  "sensor",        "energy", "total_increasing", None),
    (1, 0, 2, 8, 0, 255):    _e("energy_export_total", "Cumulative Export Energy Total",  "Wh",  "sensor",        "energy", "total_increasing", None),
    (0, 0, 96, 13, 0, 255):  _e("consumer_message",    "Consumer Message",                None,  "sensor",        None,     None,               "diagnostic"),
}


def find_frame_start(buf: bytes) -> int:
    """Return index of the first 0x0F byte (DLMS data-notification tag), or -1."""
    return buf.find(0x0F)


def decode_octet_string(raw: bytes) -> str:
    """Decode raw bytes to a string. Strips trailing null bytes (meter uses fixed-size padded fields)."""
    raw = raw.rstrip(b"\x00")
    if not raw:
        return ""
    try:
        return raw.decode("ascii")
    except (UnicodeDecodeError, ValueError):
        pass
    try:
        return raw.decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        pass
    return raw.hex(":")


def _parse_typed_value(data: bytes, pos: int) -> tuple[Any, int]:
    """Parse one DLMS typed value at pos. Returns (value, new_pos)."""
    if pos >= len(data):
        raise FrameParseError(f"Unexpected end of data at position {pos}")

    type_tag = data[pos]
    pos += 1

    if type_tag == _DTYPE_NULL:
        return None, pos

    if type_tag == _DTYPE_DOUBLE_LONG_UNSIGNED:
        if pos + 4 > len(data):
            raise FrameParseError(f"Truncated uint32 at position {pos}")
        value = int.from_bytes(data[pos : pos + 4], "big")
        return value, pos + 4

    if type_tag == _DTYPE_OCTET_STRING:
        if pos >= len(data):
            raise FrameParseError(f"Missing octet-string length at position {pos}")
        length = data[pos]
        pos += 1
        if pos + length > len(data):
            raise FrameParseError(f"Truncated octet-string (need {length} bytes) at position {pos}")
        raw = data[pos : pos + length]
        return decode_octet_string(raw), pos + length

    if type_tag in (_DTYPE_ENUM, _DTYPE_ENUM_ALT):
        if pos >= len(data):
            raise FrameParseError(f"Missing enum value at position {pos}")
        return data[pos], pos + 1

    if type_tag == _DTYPE_VENDOR_WRAP:
        # Vendor-specific prefix (0x62) — the real typed value follows immediately.
        return _parse_typed_value(data, pos)

    ctx_start = max(0, pos - 3)
    ctx = data[ctx_start : min(len(data), pos + 8)]
    raise FrameParseError(
        f"Unknown type tag 0x{type_tag:02X} at position {pos - 1}, context: {ctx.hex(' ')}"
    )


def parse_frame(data: bytes) -> ParseResult:
    """Parse a DLMS data-notification push frame into a ParseResult."""
    if len(data) < 8:
        raise FrameParseError(f"Frame too short: {len(data)} bytes")
    if data[0] != 0x0F:
        raise FrameParseError(f"Expected 0x0F frame marker, got 0x{data[0]:02X}")

    invoke_id = int.from_bytes(data[1:5], "big")
    pos = 6  # skip tag(1) + invoke-id(4) + datetime-flag(1)

    # Outer structure(2)
    if pos + 2 > len(data) or data[pos] != 0x02 or data[pos + 1] != 0x02:
        raise FrameParseError(
            f"Expected outer structure(2) at position {pos}, got: {data[pos:pos+2].hex(' ')}"
        )
    pos += 2

    # First element: notification type enum
    if pos + 2 > len(data) or data[pos] != _DTYPE_ENUM:
        raise FrameParseError(f"Expected enum tag 0x{_DTYPE_ENUM:02X} at position {pos}")
    notification_type = data[pos + 1]
    pos += 2

    # Second element: array with N items
    if pos + 2 > len(data) or data[pos] != 0x01:
        raise FrameParseError(f"Expected array tag 0x01 at position {pos}")
    item_count = data[pos + 1]
    pos += 2

    log.debug(
        "Parsing frame: invoke_id=0x%08X notification_type=%d items=%d",
        invoke_id, notification_type, item_count,
    )

    values: dict = {}

    for i in range(item_count):
        # Inner structure(2)
        if pos + 2 > len(data) or data[pos] != 0x02 or data[pos + 1] != 0x02:
            raise FrameParseError(
                f"Expected inner structure(2) for item {i} at position {pos}"
            )
        pos += 2

        # 9-byte OBIS descriptor: class_id(2) + obis(6) + attribute(1)
        if pos + 9 > len(data):
            raise FrameParseError(f"Truncated OBIS descriptor for item {i} at position {pos}")
        class_id = int.from_bytes(data[pos : pos + 2], "big")
        obis = tuple(data[pos + 2 : pos + 8])
        attribute = data[pos + 8]
        pos += 9

        # Typed value
        try:
            raw_value, pos = _parse_typed_value(data, pos)
        except FrameParseError as exc:
            raise FrameParseError(f"Item {i} OBIS {obis}: {exc}") from exc

        entry = OBIS_REGISTRY.get(obis)
        if entry is None:
            log.warning(
                "Unknown OBIS %s (class=%d attr=%d) — skipping", obis, class_id, attribute
            )
            continue

        # Map enum integers to status strings for binary_sensor fields
        if entry.ha_domain == "binary_sensor" and isinstance(raw_value, int):
            raw_value = _ENUM_STATUS.get(raw_value, "disconnected")

        values[entry.key] = ParsedValue(
            obis=obis,
            class_id=class_id,
            attribute=attribute,
            raw_value=raw_value,
            entry=entry,
        )
        log.debug("  %s = %r", entry.key, raw_value)

    return ParseResult(invoke_id=invoke_id, notification_type=notification_type, values=values)
