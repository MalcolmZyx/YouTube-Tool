{#
  Likes and dislikes can legitimately be slightly negative in a period export (a reaction removed in the period), so
  this only WARNS: a negative value is shown in the test output without failing the build. If many videos are
  negative, or one is very negative, the export is probably not what we think it is and this should be looked at.
#}
{{ config(severity='warn') }}

select upload_id, video_id, metric_key, value
from {{ ref('stg_video_metric') }}
where metric_key in ('likes', 'dislikes')
  and value < 0
