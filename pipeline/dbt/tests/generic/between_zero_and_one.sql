{# Passes when every non-null value is a proportion: at least 0 and at most 1. #}
{% test between_zero_and_one(model, column_name) %}

select {{ column_name }} from {{ model }} where {{ column_name }} < 0 or {{ column_name }} > 1

{% endtest %}
