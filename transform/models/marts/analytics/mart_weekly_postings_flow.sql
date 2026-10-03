-- Postings opened / closed / listed per ISO week (weeks start on Monday).
-- "opened" excludes left-censored spells: a posting already listed the first time we looked
-- at its board did not open that week, we just started watching.
with weeks as (
    select distinct {{ week_start('snapshot_date') }} as week_start
    from {{ ref('stg_bronze__extract_manifests') }}
    where status = 'ok'
),

opened as (
    select
        {{ week_start('first_seen') }} as week_start,
        count(*) filter (where not is_left_censored) as opened,
        count(*) filter (where spell_number > 1) as reopened
    from {{ ref('fct_postings') }}
    group by 1
),

closed as (
    select {{ week_start('closed_at') }} as week_start, count(*) as closed
    from {{ ref('fct_postings') }}
    where closed_at is not null
    group by 1
),

listed as (
    select
        {{ week_start('snapshot_date') }} as week_start,
        count(distinct posting_key) as listed_postings,
        count(distinct company_key) as boards_observed
    from {{ ref('fct_posting_daily') }}
    group by 1
)

select
    weeks.week_start,
    coalesce(listed.boards_observed, 0) as boards_observed,
    coalesce(listed.listed_postings, 0) as listed_postings,
    coalesce(opened.opened, 0) as opened,
    coalesce(opened.reopened, 0) as reopened,
    coalesce(closed.closed, 0) as closed,
    coalesce(opened.opened, 0) - coalesce(closed.closed, 0) as net_change
from weeks
left join opened on opened.week_start = weeks.week_start
left join closed on closed.week_start = weeks.week_start
left join listed on listed.week_start = weeks.week_start
order by weeks.week_start
