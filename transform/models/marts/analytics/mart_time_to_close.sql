-- How long postings stay listed before closing, per role family plus an all-roles row.
-- days_to_close = closed_at - first_seen, i.e. measured at snapshot resolution (an upper
-- bound: the posting actually vanished somewhere between last_seen and closed_at).
-- Left-censored spells (already open at the first snapshot) are excluded; still-open spells
-- are right-censored and only counted, which biases the median low - see DESIGN.md.
select
    case when grouping(role_family) = 1 then 'all_roles' else role_family end as role_family,
    count(*) filter (where closed_at is not null and not is_left_censored) as closed_spells,
    count(*) filter (where is_open) as still_open_spells,
    count(*) filter (where closed_at is not null and is_left_censored) as excluded_left_censored,
    round(avg(days_to_close) filter (where not is_left_censored), 1) as mean_days_to_close,
    median(days_to_close) filter (where not is_left_censored) as median_days_to_close,
    quantile_cont(days_to_close, 0.75) filter (where not is_left_censored) as p75_days_to_close,
    max(days_to_close) filter (where not is_left_censored) as max_days_to_close
from {{ ref('fct_postings') }}
group by grouping sets ((role_family), ())
