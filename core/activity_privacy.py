"""Date-free presentation copies; never mutate signed evidence or scheduling state."""
import json


ACTIVITY_TIME_FIELDS = frozenset({
    'at', 'timestamp', 'created_at', 'updated_at_utc', 'generated_at', 'built_at',
    'checked_at', 'started_at', 'finished_at', 'completed_at', 'measured_at_utc',
    'attempted_at', 'last_success_at', 'last_started_at', 'last_finished_at',
    'last_activity_at', 'selected_at', 'confirmed_at', 'approved_at', 'fetched_at',
    'collected_at', 'retrieved_at', 'source_retrieved_at', 'acquired_at', 'as_of', 'created_at_utc',
})


def activity_view(value):
    """Remove activity clock fields from a new view, preserving source dates and durations.

    This is not an audit-ledger export: hashes still identify the original records.
    Never pass the view back to approval, replay-signature, or scheduling validators.
    """
    if isinstance(value, dict):
        return {key: activity_view(item) for key, item in value.items()
                if key not in ACTIVITY_TIME_FIELDS}
    if isinstance(value, (list, tuple)):
        return [activity_view(item) for item in value]
    return value


def activity_detail(text):
    """Audit details may contain JSON encoded inside a string."""
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return text
    return json.dumps(activity_view(value), ensure_ascii=False)
