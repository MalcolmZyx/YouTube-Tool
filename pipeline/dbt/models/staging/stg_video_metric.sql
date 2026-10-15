select
    vm.upload_id,
    vm.video_id,
    vm.client_id,
    vm.metric_key,
    m.display_name       as metric_name,
    m.unit,
    m.aggregation,       -- sum | ratio | weighted_avg | none: how this metric may be combined across videos
    vm.value
from {{ source('app', 'video_metric') }} as vm
inner join {{ source('app', 'metric') }} as m on m.key = vm.metric_key
