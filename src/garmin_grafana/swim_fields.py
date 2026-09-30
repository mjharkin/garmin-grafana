# %%
"""Swim-specific field mapping helpers.

Kept out of garmin_fetch.py so they can be unit-tested without a Garmin login or an
InfluxDB connection - garmin_fetch.py connects to InfluxDB at import time.

Every constant and field name below was established by decoding a real pool swim FIT
file and comparing it against Garmin's own activity and lap data for the same activity.
The fixtures used for that comparison are deliberately NOT part of this repository:
they hold personal activity data.
"""


def activity_type_key(activity):
    """typeKey out of either the nested dict (get_activities_by_date) or a plain string."""
    activity_type = activity.get('activityType')
    if isinstance(activity_type, dict):
        return activity_type.get('typeKey')
    return activity_type


def is_swim_type(activity_type):
    return 'swim' in str(activity_type or '').lower()


def _num(mapping, *keys):
    """First non-None value among keys, as float.

    InfluxDB fixes a field's type at its first write, so every numeric field is emitted
    as a float: sending 42 after 42.0 is rejected as a field type conflict. Same class
    of bug as the ActivityLap.Sport cast in #277.
    """
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return float(value)
    return None


def swim_summary_fields(activity, activity_type=None):
    """Session-level swim metrics, from the daily summary call the sync already makes.

    Returns {} for anything that is not a swim, so callers can update() unconditionally.
    Works for activities whose FIT file is not processed, so it also covers the
    historical pool swims that have no detail rows.

    Unit trap: poolLength is in CENTIMETRES in the flattened get_activities_by_date()
    dict (2500.0 = 25 m), but in metres in get_activity()['summaryDTO'] (25.0). Only the
    centimetre form reaches this function; the sanity check keeps it idempotent if that
    ever changes.
    """
    if not is_swim_type(activity_type or activity_type_key(activity)):
        return {}
    pool_length = _num(activity, 'poolLength')
    if pool_length is not None and pool_length > 200:
        pool_length = pool_length / 100.0
    return {
        'totalStrokes': _num(activity, 'strokes', 'totalNumberOfStrokes'),
        'averageSWOLF': _num(activity, 'averageSwolf', 'averageSWOLF'),
        'averageSwimCadence': _num(activity, 'averageSwimCadenceInStrokesPerMinute', 'averageSwimCadence'),
        'avgStrokesPerLength': _num(activity, 'avgStrokes', 'averageStrokes'),
        'activeLengths': _num(activity, 'activeLengths', 'numberOfActiveLengths'),
        'poolLength': pool_length,
    }


def _is_swim_lap(lap):
    """Decide from the lap itself, never from a key merely being present.

    A run's laps carry unknown_73 / num_lengths / num_active_lengths as keys whose value
    is None, so a presence test would tag running laps with empty swim fields.
    """
    if 'swim' in str(lap.get('sport', '')).lower() or 'swim' in str(lap.get('sub_sport', '')).lower():
        return True
    return any(lap.get(key) is not None for key in ('swim_stroke', 'num_lengths', 'num_active_lengths'))


def swim_lap_fields(lap):
    """Swim-only per-lap fields; {} for every other sport.

    SWOLF is not in the FIT profile at all, so fitparse leaves it as the numeric field
    `unknown_73` and the official SDK does the same. Identified by comparison with
    Garmin's own lap data for the same activity, where it equals the reported
    averageSWOLF lap for lap, on every lap with a distance.

    Per-lap strokes live in `total_cycles`: fitparse resolves neither `total_work` nor
    its `total_strokes` subfield (both None), and total_cycles matches Garmin's reported
    stroke count lap for lap.
    """
    if not _is_swim_lap(lap):
        return {}
    swolf = lap.get('unknown_73')
    return {
        'SWOLF': float(swolf) if swolf else None,
        'Strokes': lap.get('total_cycles'),
        'Active_Lengths': lap.get('num_active_lengths'),
        'Swim_Stroke': str(lap['swim_stroke']) if lap.get('swim_stroke') else None,
        'Wkt_Step_Index': lap.get('wkt_step_index'),
    }


def swim_length_fields(length):
    """Per-length (pool length) fields.

    Only swim FIT files contain `length` messages at all, so there is no sport gate here.
    `length_type` is active | idle, which is how a swum length is told from a rest or a
    push-off.

    SWOLF is DERIVED here - the FIT carries no per-length SWOLF: elapsed + strokes, which
    was verified to agree with the device's own lap-level value.
    """
    elapsed = length.get('total_elapsed_time')
    strokes = length.get('total_strokes')
    return {
        'Elapsed_Time': elapsed,
        'Timer_Time': length.get('total_timer_time'),
        'Length_Type': str(length['length_type']) if length.get('length_type') else None,
        'Strokes': strokes,
        'Swim_Stroke': str(length['swim_stroke']) if length.get('swim_stroke') else None,
        'Avg_Speed': length.get('avg_speed'),
        'Calories': length.get('total_calories'),
        'Avg_Cadence': length.get('avg_swimming_cadence'),
        'SWOLF': float(elapsed) + float(strokes) if elapsed and strokes else None,
    }
