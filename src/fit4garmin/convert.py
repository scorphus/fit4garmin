"""FIT file conversion: re-encode a non-Garmin activity as a Garmin one.

Garmin Connect only calculates Training Effect / training load for
activities recorded by Garmin devices. Rewriting the manufacturer in
file_id and device_info is enough — Garmin recalculates everything else
from the raw HR data.
"""

from garmin_fit_sdk import Decoder, Encoder, Stream

GARMIN_PRODUCT = 4565  # Edge 1050

MESG_NUMS = {
    "file_id_mesgs": 0,
    "file_creator_mesgs": 1,
    "device_settings_mesgs": 2,
    "user_profile_mesgs": 3,
    "zones_target_mesgs": 7,
    "hr_zone_mesgs": 8,
    "power_zone_mesgs": 9,
    "sport_mesgs": 12,
    "session_mesgs": 18,
    "lap_mesgs": 19,
    "record_mesgs": 20,
    "event_mesgs": 21,
    "device_info_mesgs": 23,
    "workout_mesgs": 26,
    "activity_mesgs": 34,
    "segment_lap_mesgs": 142,
}

PROCESS_ORDER = [
    "file_id_mesgs",
    "file_creator_mesgs",
    "device_settings_mesgs",
    "user_profile_mesgs",
    "zones_target_mesgs",
    "hr_zone_mesgs",
    "power_zone_mesgs",
    "sport_mesgs",
    "device_info_mesgs",
    "workout_mesgs",
    "event_mesgs",
    "record_mesgs",
    "segment_lap_mesgs",
    "lap_mesgs",
    "session_mesgs",
    "activity_mesgs",
]


def convert_fit_bytes(data: bytes, with_info: bool = False):
    """Convert FIT file bytes: spoof manufacturer to Garmin.

    With with_info=True, returns (bytes, info) where info carries the
    session start_time (UTC datetime) for locating the activity on
    Garmin Connect after upload.
    """
    stream = Stream.from_byte_array(bytearray(data))
    decoder = Decoder(stream)
    messages, errors = decoder.read()

    if errors:
        raise ValueError(f"Errors reading FIT file: {errors}")

    sessions = messages.get("session_mesgs") or []
    info = {"start_time": sessions[0].get("start_time") if sessions else None}

    encoder = Encoder()

    for msg_type in PROCESS_ORDER:
        mesg_num = MESG_NUMS.get(msg_type)
        if mesg_num is None:
            continue

        for msg in messages.get(msg_type, []):
            m = {"mesg_num": mesg_num}
            m.update({k: v for k, v in msg.items() if k != "developer_fields"})

            if msg_type == "file_id_mesgs":
                m["manufacturer"] = "garmin"
                m["garmin_product"] = GARMIN_PRODUCT
                for k in ("product", "product_name"):
                    m.pop(k, None)

            if msg_type == "device_info_mesgs":
                if m.get("device_index") in ("creator", 0):
                    m["manufacturer"] = "garmin"
                    m["garmin_product"] = GARMIN_PRODUCT
                    for k in ("product", "product_name", "descriptor"):
                        m.pop(k, None)

            encoder.write_mesg(m)

    result = bytes(encoder.close())
    return (result, info) if with_info else result


def convert_fit(input_path: str, output_path: str) -> dict:
    """Convert a FIT file on disk. Returns stats dict."""
    with open(input_path, "rb") as f:
        data = f.read()

    result = convert_fit_bytes(data)

    with open(output_path, "wb") as f:
        f.write(result)

    return {"output_size": len(result)}
