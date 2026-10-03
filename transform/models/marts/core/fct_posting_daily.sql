{#-
  Snapshot fact: one row per posting per successful board snapshot ("posting X was listed
  on board B on date D"). Incremental with partition-overwrite semantics: each run
  rebuilds only the (board, snapshot_date) partitions whose bronze extraction is new or was
  re-landed (a different landing_id = extracted_at + content hash), deleting and
  re-inserting that whole partition.

  The pre-hook first deletes every loaded row whose partition is no longer the current ok
  landing. delete+insert alone would miss a partition re-landed with zero postings, because
  an empty batch has no keys to delete.

  Only postings that passed the extract contract appear here; listed-but-rejected ones are
  in stg_bronze__unparsed_postings and only affect the lifecycle (fct_postings).
-#}
{{ config(
    materialized='incremental',
    unique_key=['company_key', 'snapshot_date'],
    incremental_strategy='delete+insert',
    on_schema_change='fail',
    pre_hook="{{ delete_stale_daily_partitions() }}",
) }}

with ok_snapshots as (
    select company_key, snapshot_date, extracted_at, landing_id
    from {{ ref('stg_bronze__extract_manifests') }}
    where status = 'ok'
),

{% if is_incremental() %}
pending_partitions as (
    select ok_snapshots.*
    from ok_snapshots
    where not exists (
        select 1
        from {{ this }} as loaded
        where loaded.company_key = ok_snapshots.company_key
            and loaded.snapshot_date = ok_snapshots.snapshot_date
            and loaded.landing_id = ok_snapshots.landing_id
    )
),
{% else %}
pending_partitions as (
    select * from ok_snapshots
),
{% endif %}

postings as (
    select * from {{ ref('int_postings__classified') }}
)

select
    postings.posting_key,
    postings.company_key,
    postings.source,
    postings.board,
    postings.posting_id,
    postings.snapshot_date,
    postings.extracted_at,
    postings.title,
    postings.department,
    postings.role_family,
    postings.seniority,
    postings.is_entry_level,
    postings.employment_type,
    postings.workplace_type,
    postings.location_key,
    postings.published_at,
    pending_partitions.landing_id
from postings
inner join pending_partitions
    on pending_partitions.company_key = postings.company_key
    and pending_partitions.snapshot_date = postings.snapshot_date
    and pending_partitions.extracted_at = postings.extracted_at
