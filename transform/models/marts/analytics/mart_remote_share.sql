-- Workplace mix of listed postings per week (one observation per posting per week).
with weekly as (
    select
        {{ week_start('snapshot_date') }} as week_start,
        posting_key,
        workplace_type
    from {{ ref('fct_posting_daily') }}
    qualify row_number() over (
        partition by {{ week_start('snapshot_date') }}, posting_key
        order by snapshot_date desc
    ) = 1
)

select
    week_start,
    count(*) as listed_postings,
    count(*) filter (where workplace_type = 'remote') as remote_postings,
    count(*) filter (where workplace_type = 'hybrid') as hybrid_postings,
    count(*) filter (where workplace_type = 'onsite') as onsite_postings,
    count(*) filter (where workplace_type = 'unknown') as unknown_postings,
    round(count(*) filter (where workplace_type = 'remote') / count(*), 4) as remote_share,
    round(count(*) filter (where workplace_type = 'hybrid') / count(*), 4) as hybrid_share
from weekly
group by week_start
order by week_start
