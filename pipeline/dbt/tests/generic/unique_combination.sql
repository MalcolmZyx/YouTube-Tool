{#
  Passes when no combination of the given columns appears twice (a composite key). Used for the grains of the marts,
  for example one row per upload and video.
#}
{% test unique_combination(model, columns) %}

select {{ columns | join(', ') }}, count(*) as rows_with_this_key
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1

{% endtest %}
