{# A click-through rate in percent lies between 0 and 100. #}
select upload_id, video_id, impressions_ctr_pct
from {{ ref('mart_video_performance') }}
where impressions_ctr_pct < 0 or impressions_ctr_pct > 100
