{#- Schema (DuckDB) / dataset (BigQuery) names per layer.

    DuckDB: the custom schema as-is (staging, intermediate, core, analytics, reference) so
    the local warehouse is easy to query.
    BigQuery: "<target dataset>_<custom>", e.g. job_market_staging, job_market_core. Those
    are exactly the datasets infra/gcp declares and grants the service account on, so dbt
    never needs permission to create datasets. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- elif target.type == 'bigquery' -%}
        {{ target.schema }}_{{ custom_schema_name | trim }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
