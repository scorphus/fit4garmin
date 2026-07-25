"""Garmin Connect helpers shared by the web app and the CLI."""

import time
from datetime import datetime, timezone

ACTIVITY_URL = "https://connect.garmin.com/modern/activity/{}"


def find_activity_id(garmin, start_time, attempts: int = 4, delay: float = 1.5):
    """Locate an activity on Garmin Connect by its start time.

    Garmin processes uploads asynchronously and the upload response does
    not carry the activity id, so we poll the activity list and match on
    startTimeGMT (within 10 seconds). Returns the id or None.
    """
    if start_time is None:
        return None
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    for attempt in range(attempts):
        if attempt:
            time.sleep(delay)
        try:
            for act in garmin.get_activities(0, 10):
                gmt = act.get("startTimeGMT")
                if not gmt:
                    continue
                act_time = datetime.strptime(gmt, "%Y-%m-%d %H:%M:%S").replace(
                    tzinfo=timezone.utc
                )
                if abs((act_time - start_time).total_seconds()) <= 10:
                    return act.get("activityId")
        except Exception:
            pass
    return None


def activity_url(activity_id) -> str | None:
    return ACTIVITY_URL.format(activity_id) if activity_id else None
