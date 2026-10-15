{# Uploads per month for each client, from the client's latest export. Months with no upload are simply absent. #}
select
    client_id,
    date_trunc('month', published_on)::date            as month,
    count(*)                                           as uploads,
    count(*) filter (where is_short)                   as shorts,
    count(*) filter (where not is_short)               as long_form,
    sum(views)                                         as views_of_those_uploads
from {{ ref('mart_video_performance') }}
where is_latest_upload
  and published_on is not null
group by client_id, date_trunc('month', published_on)
