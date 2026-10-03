{#-
  Read one bronze dataset (postings | manifests | rejects) straight from the local lake.
  The Hive partition columns source / board / snapshot_date come from the directory names,
  so a filter on snapshot_date lets DuckDB skip whole files. DuckDB-specific by design:
  on BigQuery the same role is played by a table loaded from GCS (see profiles.yml).
  The directory is spliced into a SQL string literal, so single quotes are doubled.
-#}
{% macro bronze_read(kind, columns) -%}
read_json(
    '{{ env_var("JOBPIPE_BRONZE_DIR", "../data/bronze") | replace("'", "''") }}/{{ kind }}/*/*/*/*.jsonl',
    format = 'newline_delimited',
    hive_partitioning = true,
    hive_types = {'snapshot_date': 'DATE'},
    columns = {
    {%- for name, type in columns.items() %}
        '{{ name }}': '{{ type }}'{{ "," if not loop.last }}
    {%- endfor %}
    }
)
{%- endmacro %}
