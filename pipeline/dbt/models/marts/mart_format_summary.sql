{#
  Shorts against long-form, per upload. Descriptive only: the significance test and the confidence range are in the
  Python audit. Rates are never averaged across videos: the click rate is weighted by impressions, and a video with no
  impressions (usually a Short) is left out of it rather than counted as 0%.
#}
select
    upload_id,
    client_id,
    is_short,
    count(*)                                                        as videos,
    sum(views)                                                      as total_views,
    percentile_cont(0.5) within group (order by views)              as median_views,
    sum(impressions)                                                as total_impressions,
    sum(impressions_ctr_pct * impressions) filter (where impressions > 0)
        / nullif(sum(impressions) filter (where impressions > 0 and impressions_ctr_pct is not null), 0) as weighted_ctr_pct,
    percentile_cont(0.5) within group (order by avg_percentage_viewed_pct) as median_percent_viewed
from {{ ref('mart_video_performance') }}
where is_short is not null
group by upload_id, client_id, is_short
