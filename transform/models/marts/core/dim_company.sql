-- One row per (provider, board) with extraction health.
with manifests as (
    select * from {{ ref('stg_bronze__extract_manifests') }}
),

postings as (
    select company_key, count(distinct posting_key) as postings_seen
    from {{ ref('fct_posting_daily') }}
    group by company_key
)

select
    manifests.company_key,
    any_value(manifests.source) as source,
    any_value(manifests.board) as board,
    arg_max(manifests.company, manifests.snapshot_date) as company_name,
    min(manifests.snapshot_date) as first_snapshot_date,
    max(manifests.snapshot_date) filter (where manifests.status = 'ok') as last_ok_snapshot_date,
    count(*) filter (where manifests.status = 'ok') as ok_snapshots,
    count(*) filter (where manifests.status <> 'ok') as failed_snapshots,
    coalesce(sum(manifests.reject_count), 0) as rejected_records,
    coalesce(any_value(postings.postings_seen), 0) as postings_seen
from manifests
left join postings on postings.company_key = manifests.company_key
group by manifests.company_key
