{#
  One row per video per upload, wide: a column per headline metric. The long `video_metric` table is pivoted with
  conditional aggregation. A metric a video does not have stays NULL (not reported), never 0.
  To add a column, add its metric key to the list below.
#}
{% set metrics = [
    'views', 'engaged_views', 'impressions', 'impressions_ctr_pct', 'watch_time_hours',
    'avg_view_duration_seconds', 'avg_percentage_viewed_pct', 'likes', 'shares', 'comments_added',
    'subscribers_gained', 'subscribers_lost', 'subscribers_net',
] %}

with pivoted as (

    select
        upload_id,
        video_id,
        {% for metric in metrics %}
        max(case when metric_key = '{{ metric }}' then value end) as {{ metric }}{{ "," if not loop.last }}
        {% endfor %}
    from {{ ref('stg_video_metric') }}
    group by upload_id, video_id

)

select
    u.upload_id,
    u.client_id,
    v.video_id,
    v.youtube_video_id,
    v.title,
    v.published_on,
    v.duration_seconds,
    v.is_short,
    u.as_of_date,
    u.is_latest_upload,
    u.as_of_date - v.published_on                       as age_days,
    p.views / nullif(u.as_of_date - v.published_on, 0)  as views_per_day,
    {% for metric in metrics %}
    p.{{ metric }}{{ "," if not loop.last }}
    {% endfor %}
from pivoted as p
inner join {{ ref('stg_upload') }} as u on u.upload_id = p.upload_id
inner join {{ ref('stg_video') }}  as v on v.video_id  = p.video_id and v.client_id = u.client_id
