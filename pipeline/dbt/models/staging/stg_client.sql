select
    id                                  as client_id,
    name                                as client_name,
    coalesce(notes = '[synthetic]', false) as is_synthetic,   -- fake demo channels are marked in their notes
    created_at
from {{ source('app', 'client') }}
