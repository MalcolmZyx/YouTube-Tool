{#
  A count metric (views, shares, ...) can never be negative: a negative one means a broken import.

  Not covered here, on purpose: subscribers_net (gained minus lost), and the reaction counts likes and dislikes. In a
  period export those reflect the change over the period, so one can be negative when a reaction is removed. The real
  sample export has a video with Dislikes = -1. Those are watched by assert_reaction_counts_negative_is_rare instead.
#}
select upload_id, video_id, metric_key, value
from {{ ref('stg_video_metric') }}
where unit = 'count'
  and aggregation = 'sum'
  and metric_key not in ('subscribers_net', 'likes', 'dislikes')
  and value < 0
