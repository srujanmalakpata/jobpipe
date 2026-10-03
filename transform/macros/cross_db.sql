{#-
  Dialect-sensitive expressions live behind adapter.dispatch so models stay portable.
  The duckdb implementations are what the pipeline runs and tests. The bigquery ones are
  written for the documented cloud target but have NOT been executed (no GCP account).
-#}

{% macro json_str(column, path) -%}
    {{ return(adapter.dispatch('json_str', 'job_market')(column, path)) }}
{%- endmacro %}
{% macro default__json_str(column, path) -%}
    json_extract_string({{ column }}, '{{ path }}')
{%- endmacro %}
{% macro bigquery__json_str(column, path) -%}
    json_value({{ column }}, '{{ path }}')
{%- endmacro %}

{% macro regex_contains(text, pattern) -%}
    {{ return(adapter.dispatch('regex_contains', 'job_market')(text, pattern)) }}
{%- endmacro %}
{% macro default__regex_contains(text, pattern) -%}
    regexp_matches({{ text }}, {{ pattern }})
{%- endmacro %}
{% macro bigquery__regex_contains(text, pattern) -%}
    regexp_contains({{ text }}, {{ pattern }})
{%- endmacro %}

{% macro week_start(date_expr) -%}
    {{ return(adapter.dispatch('week_start', 'job_market')(date_expr)) }}
{%- endmacro %}
{% macro default__week_start(date_expr) -%}
    cast(date_trunc('week', {{ date_expr }}) as date)
{%- endmacro %}
{% macro bigquery__week_start(date_expr) -%}
    date_trunc({{ date_expr }}, isoweek)
{%- endmacro %}

{% macro days_between(start_date, end_date) -%}
    {{ return(adapter.dispatch('days_between', 'job_market')(start_date, end_date)) }}
{%- endmacro %}
{% macro default__days_between(start_date, end_date) -%}
    date_diff('day', {{ start_date }}, {{ end_date }})
{%- endmacro %}
{% macro bigquery__days_between(start_date, end_date) -%}
    date_diff({{ end_date }}, {{ start_date }}, day)
{%- endmacro %}

{% macro to_utc_timestamp(text_expr) -%}
    {{ return(adapter.dispatch('to_utc_timestamp', 'job_market')(text_expr)) }}
{%- endmacro %}
{% macro default__to_utc_timestamp(text_expr) -%}
    cast(cast({{ text_expr }} as timestamptz) as timestamp)
{%- endmacro %}
{% macro bigquery__to_utc_timestamp(text_expr) -%}
    datetime(timestamp({{ text_expr }}))
{%- endmacro %}
