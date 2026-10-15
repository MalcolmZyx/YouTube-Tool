{# Passes when every non-null value is greater than zero. #}
{% test positive(model, column_name) %}

select {{ column_name }} from {{ model }} where {{ column_name }} <= 0

{% endtest %}
