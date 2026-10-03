-- Share of listed postings that are internships / co-ops or entry-level, per week and
-- role family (plus an all-roles row per week).
with weekly as (
    select
        {{ week_start('snapshot_date') }} as week_start,
        posting_key,
        role_family,
        seniority,
        is_entry_level
    from {{ ref('fct_posting_daily') }}
    qualify row_number() over (
        partition by {{ week_start('snapshot_date') }}, posting_key
        order by snapshot_date desc
    ) = 1
)

select
    week_start,
    case when grouping(role_family) = 1 then 'all_roles' else role_family end as role_family,
    count(*) as listed_postings,
    count(*) filter (where seniority = 'intern') as intern_postings,
    count(*) filter (where is_entry_level) as entry_level_postings,
    round(count(*) filter (where is_entry_level) / count(*), 4) as entry_level_share
from weekly
group by grouping sets ((week_start, role_family), (week_start))
