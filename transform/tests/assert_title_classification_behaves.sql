-- Every example in title_classification_cases must get the stated role family and
-- seniority. Mirrors int_postings__classified: the first matching role rule by priority
-- (else 'other') and the classify_seniority macro on the title alone.
with cases as (
    select * from {{ ref('title_classification_cases') }}
),

role_matches as (
    select
        cases.title,
        rules.role_family,
        row_number() over (partition by cases.title order by rules.priority) as match_rank
    from cases
    inner join {{ ref('role_family_rules') }} as rules
        on {{ regex_contains('lower(cases.title)', 'rules.pattern') }}
),

actual as (
    select
        cases.title,
        cases.role_family as expected_role_family,
        coalesce(role_matches.role_family, 'other') as actual_role_family,
        cases.seniority as expected_seniority,
        {{ classify_seniority('cases.title', "'unknown'") }} as actual_seniority
    from cases
    left join role_matches
        on role_matches.title = cases.title
        and role_matches.match_rank = 1
)

select *
from actual
where actual_role_family <> expected_role_family
   or actual_seniority <> expected_seniority
