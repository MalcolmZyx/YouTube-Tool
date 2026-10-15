{#
  One row per imported export, plus the two derived facts every mart needs:
    * as_of_date: the day video ages are measured against. The same rule as the Python audit (audit/service.py):
      the end of a known date range, else the export date the operator gave, else the day it was imported.
    * is_latest_upload: the newest upload of that client, which is what a dashboard normally shows.
#}
with uploads as (

    select * from {{ source('app', 'upload') }}

)

select
    id                                              as upload_id,
    client_id,
    original_filename,
    report_type,
    period_kind,
    period_start,
    period_end,
    imported_at,
    row_count,
    case
        when period_kind = 'range' and period_end is not null then period_end
        when exported_on is not null                          then exported_on
        else imported_at::date
    end                                             as as_of_date,
    case
        when period_kind = 'range' and period_end is not null then 'period_end'
        when exported_on is not null                          then 'exported_on'
        else 'imported_at'
    end                                             as as_of_source,
    row_number() over (partition by client_id order by imported_at desc, id desc) = 1 as is_latest_upload
from uploads
