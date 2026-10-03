-- Postings that were listed in a successful snapshot but failed the extract contract
-- (quarantined to bronze/rejects). They carry no usable attributes, but they *were* on the
-- board that day, so the lifecycle model must not treat them as closed.
with rejected_ids as (
    select
        company_key,
        source,
        board,
        snapshot_date,
        unnest(rejected_posting_ids) as posting_id
    from {{ ref('stg_bronze__extract_manifests') }}
    where status = 'ok'
)

select distinct
    company_key,
    source,
    board,
    snapshot_date,
    posting_id,
    company_key || ':' || posting_id as posting_key
from rejected_ids
