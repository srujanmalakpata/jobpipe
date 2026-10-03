{#-
  Helpers shared by the incremental core facts and their pre-hooks.

  dbt's delete+insert strategy only deletes keys that appear in the *new* batch. When a
  partition is re-landed with zero postings (or a recomputed board yields zero spells), the
  batch has no rows for it and the old rows would survive. The pre-hooks below delete every
  loaded row that no longer matches the current bronze state, before the model inserts.
-#}

{#- One row per board: md5 over its successful (snapshot_date, landing_id) list, so any
    new, removed, re-landed or content-changed ok snapshot changes the watermark. -#}
{% macro ok_board_watermarks() -%}
select
    company_key,
    md5(string_agg(
        cast(snapshot_date as {{ dbt.type_string() }}) || '@' || landing_id, ','
        order by snapshot_date
    )) as board_watermark
from {{ ref('stg_bronze__extract_manifests') }}
where status = 'ok'
group by company_key
{%- endmacro %}

{#- fct_posting_daily: drop rows whose (board, day) is no longer the current ok landing
    (a different landing_id: new extracted_at and/or different content). -#}
{% macro delete_stale_daily_partitions() -%}
{%- if is_incremental() %}
delete from {{ this }}
where not exists (
    select 1
    from {{ ref('stg_bronze__extract_manifests') }} as manifests
    where manifests.status = 'ok'
        and manifests.company_key = {{ this }}.company_key
        and manifests.snapshot_date = {{ this }}.snapshot_date
        and manifests.landing_id = {{ this }}.landing_id
)
{%- endif %}
{%- endmacro %}

{#- fct_postings: drop every spell of a board whose watermark changed (or vanished). -#}
{% macro delete_stale_board_spells() -%}
{%- if is_incremental() %}
delete from {{ this }}
where not exists (
    select 1
    from ({{ ok_board_watermarks() }}) as current_marks
    where current_marks.company_key = {{ this }}.company_key
        and current_marks.board_watermark = {{ this }}.board_watermark
)
{%- endif %}
{%- endmacro %}
