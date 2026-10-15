select
    ut.upload_id,
    ut.client_id,
    ut.metric_key,
    m.display_name       as metric_name,
    m.unit,
    ut.value
from {{ source('app', 'upload_total') }} as ut
inner join {{ source('app', 'metric') }} as m on m.key = ut.metric_key
