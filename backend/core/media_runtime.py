"""One definition of a Media row's runtime for SQL aggregates (watch time,
average runtime). Episodes often carry their runtime only in
tmdb_data['runtime'], while movies use the Media.runtime column."""

from sqlalchemy import case, func
from sqlalchemy.types import Integer as SAInteger, Text as SAText

from models.events import WatchEvent
from models.media import Media


def effective_runtime_expression():
    """Media.runtime, falling back to the cached tmdb_data runtime.

    Extract the JSON scalar as text so both numeric and string runtime values
    can be cast. The in-Python counterpart for a single row is
    routers.history._effective_runtime."""
    json_runtime = func.cast(
        func.nullif(Media.tmdb_data["runtime"].as_string(), "null"),
        SAInteger,
    )
    return func.coalesce(func.nullif(Media.runtime, 0), func.nullif(json_runtime, 0))


def effective_watch_time_expression():
    """Minutes represented by one completed WatchEvent row, including repeats."""
    plays_per_event = case(
        (WatchEvent.play_count > 1, WatchEvent.play_count),
        else_=1,
    )
    return effective_runtime_expression() * plays_per_event
