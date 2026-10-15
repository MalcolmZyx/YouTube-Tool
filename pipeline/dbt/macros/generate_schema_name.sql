{#
  By default dbt names a model's schema "<target schema>_<custom schema>" (analytics_staging). Use the custom schema
  as written instead, so the layers are simply `staging` and `marts`.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
