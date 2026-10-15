select
    id                                  as video_id,
    client_id,
    youtube_video_id,
    title,
    published_on,
    duration_seconds,
    -- The export has no "is a Short" flag, so 60 seconds or less is the proxy (same rule as the Python audit).
    duration_seconds <= 60              as is_short
from {{ source('app', 'video') }}
