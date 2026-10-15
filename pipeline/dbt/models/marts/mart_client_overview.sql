{#
  One row per client: the headline numbers of its latest export, and two honest cross-checks.
    * listed_vs_total_gap_share: the export's own Total can exceed the sum over listed videos (deleted videos, activity
      credited to the channel). A big gap means the video table does not tell the whole story.
    * top_decile_share: how much of the listed views the top 10% of videos hold.
#}
with latest as (

    select * from {{ ref('stg_upload') }} where is_latest_upload

),

ranked as (

    select
        p.upload_id,
        p.views,
        row_number() over (partition by p.upload_id order by p.views desc nulls last) as rank_by_views,
        count(*)     over (partition by p.upload_id)                                  as videos_in_upload
    from {{ ref('mart_video_performance') }} as p
    where p.views is not null

),

concentration as (

    select
        upload_id,
        count(*)                                                                      as videos_with_views,
        sum(views)                                                                    as listed_views,
        sum(views) filter (where rank_by_views <= ceil(videos_in_upload * 0.1))
            / nullif(sum(views), 0)                                                   as top_decile_share
    from ranked
    group by upload_id

),

totals as (

    select upload_id, value as channel_total_views
    from {{ ref('stg_upload_total') }}
    where metric_key = 'views'

)

select
    c.client_id,
    c.client_name,
    c.is_synthetic,
    l.upload_id                                                        as latest_upload_id,
    l.original_filename                                                as latest_filename,
    l.as_of_date,
    l.as_of_source,
    (select count(*) from {{ ref('stg_upload') }} u where u.client_id = c.client_id) as uploads,
    k.videos_with_views,
    k.listed_views,
    t.channel_total_views,
    (t.channel_total_views - k.listed_views) / nullif(t.channel_total_views, 0) as listed_vs_total_gap_share,
    k.top_decile_share
from {{ ref('stg_client') }} as c
left join latest        as l on l.client_id = c.client_id
left join concentration as k on k.upload_id = l.upload_id
left join totals        as t on t.upload_id = l.upload_id
