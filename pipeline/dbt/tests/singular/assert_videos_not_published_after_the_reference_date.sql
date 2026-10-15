{# A video cannot be older than zero days at the date its export is measured to (that would mean a wrong reference date). #}
select upload_id, video_id, published_on, as_of_date
from {{ ref('mart_video_performance') }}
where age_days < 0
