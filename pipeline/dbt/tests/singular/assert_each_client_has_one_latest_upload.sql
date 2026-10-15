{# Every client with uploads has exactly one latest upload; anything else would double count in the dashboards. #}
select client_id, count(*) filter (where is_latest_upload) as latest_uploads
from {{ ref('stg_upload') }}
group by client_id
having count(*) filter (where is_latest_upload) <> 1
