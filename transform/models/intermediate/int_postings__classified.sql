-- Adds role family (first matching seed rule by priority), seniority and a location key.
with postings as (
    select * from {{ ref('int_postings__unioned') }}
),

role_matches as (
    select
        postings.posting_key,
        postings.snapshot_date,
        rules.role_family,
        row_number() over (
            partition by postings.posting_key, postings.snapshot_date
            order by rules.priority
        ) as match_rank
    from postings
    inner join {{ ref('role_family_rules') }} as rules
        on {{ regex_contains('lower(postings.title)', 'rules.pattern') }}
),

classified as (
    select
        postings.*,
        coalesce(role_matches.role_family, 'other') as role_family,
        {{ classify_seniority('postings.title', 'postings.employment_type') }} as seniority,
        md5(coalesce(lower(trim(postings.location_raw)), '')) as location_key
    from postings
    left join role_matches
        on role_matches.posting_key = postings.posting_key
        and role_matches.snapshot_date = postings.snapshot_date
        and role_matches.match_rank = 1
)

select
    *,
    seniority in ('intern', 'entry') as is_entry_level
from classified
