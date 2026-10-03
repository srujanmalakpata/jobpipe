-- Skill demand: share of postings (ever seen, and currently open) that mention each skill,
-- per role family plus an all-roles rollup.
with postings as (
    select
        posting_key,
        arg_max(role_family, last_seen) as role_family,
        bool_or(is_open) as is_open
    from {{ ref('fct_postings') }}
    group by posting_key
),

totals as (
    select
        case when grouping(role_family) = 1 then 'all_roles' else role_family end
            as role_family,
        count(*) as postings_total,
        count(*) filter (where is_open) as open_total
    from postings
    group by grouping sets ((role_family), ())
),

mentions as (
    select
        case when grouping(postings.role_family) = 1 then 'all_roles' else postings.role_family end
            as role_family,
        skills.skill,
        skills.category,
        count(*) as postings_with_skill,
        count(*) filter (where postings.is_open) as open_with_skill
    from postings
    inner join {{ ref('bridge_posting_skill') }} as skills
        on skills.posting_key = postings.posting_key
    group by grouping sets (
        (postings.role_family, skills.skill, skills.category),
        (skills.skill, skills.category)
    )
)

select
    mentions.role_family,
    mentions.skill,
    mentions.category,
    mentions.postings_with_skill,
    totals.postings_total,
    round(mentions.postings_with_skill / totals.postings_total, 4) as share_of_postings,
    mentions.open_with_skill,
    totals.open_total,
    round(mentions.open_with_skill / nullif(totals.open_total, 0), 4) as share_of_open,
    rank() over (
        partition by mentions.role_family order by mentions.postings_with_skill desc
    ) as rank_in_family
from mentions
inner join totals on totals.role_family = mentions.role_family
