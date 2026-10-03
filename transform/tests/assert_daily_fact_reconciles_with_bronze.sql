-- The incremental snapshot fact must hold exactly what a full rebuild would produce today:
-- for every current ok bronze partition, the same deduplicated postings with the same
-- attributes and classification. Compared row by row (symmetric EXCEPT ALL), so this
-- catches stale rows from a re-landed or emptied partition, a missing partition, changed
-- content behind an unchanged timestamp, and drift after a role-family / seniority rule
-- change (fix that with `pipeline transform --full-refresh`). Failing rows name the
-- (board, day) partitions that differ.
with expected as (
    select
        classified.posting_key,
        classified.company_key,
        classified.snapshot_date,
        classified.extracted_at,
        classified.title,
        classified.department,
        classified.role_family,
        classified.seniority,
        classified.is_entry_level,
        classified.employment_type,
        classified.workplace_type,
        classified.location_key,
        classified.published_at,
        manifests.landing_id
    from {{ ref('int_postings__classified') }} as classified
    inner join {{ ref('stg_bronze__extract_manifests') }} as manifests
        on manifests.company_key = classified.company_key
        and manifests.snapshot_date = classified.snapshot_date
        and manifests.extracted_at = classified.extracted_at
        and manifests.status = 'ok'
),

loaded as (
    select
        posting_key,
        company_key,
        snapshot_date,
        extracted_at,
        title,
        department,
        role_family,
        seniority,
        is_entry_level,
        employment_type,
        workplace_type,
        location_key,
        published_at,
        landing_id
    from {{ ref('fct_posting_daily') }}
),

differences as (
    select 'missing_or_changed_in_fact' as problem, * from (
        select * from expected
        except all
        select * from loaded
    ) as missing
    union all
    select 'stale_in_fact' as problem, * from (
        select * from loaded
        except all
        select * from expected
    ) as stale
)

select problem, company_key, snapshot_date, count(*) as rows_affected
from differences
group by problem, company_key, snapshot_date
