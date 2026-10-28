"""Exact timestamp arithmetic and explicit timezone handling."""

from datetime import date, datetime, timedelta, timezone

from shared.errors import InputError

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
MINUTE = 60_000_000

def parse_date(value):
    # Accept ISO dates and ISO date-time strings in the DATE field, without guessing locale.
    return date.fromisoformat(value[:10])


def timestamp_us(value, assumed_zone):
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        if assumed_zone is None:
            raise InputError("timestamp has no UTC offset; specify --naive-timezone if known")
        moment = moment.replace(tzinfo=assumed_zone)
        # Refuse ambiguous/nonexistent local wall times around daylight-saving changes.
        if (moment.utcoffset() != moment.replace(fold=1).utcoffset()
                or moment.astimezone(timezone.utc).astimezone(assumed_zone).replace(tzinfo=None)
                != moment.replace(tzinfo=None)):
            raise InputError("ambiguous/nonexistent local time: supply timestamps with offsets")
    delta = moment.astimezone(timezone.utc) - EPOCH
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def iso_time(value):
    return (EPOCH + timedelta(microseconds=value)).isoformat().replace("+00:00", "Z")
