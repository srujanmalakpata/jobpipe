-- Which vocabulary skills each posting mentions (title + description of its latest
-- observation). Matching is regex over lower-cased text; see skill_pattern_cases for the
-- behaviour the patterns are tested against.
with latest as (
    select
        posting_key,
        lower(coalesce(title, '') || ' ' || coalesce(description_text, '')) as search_text
    from {{ ref('int_postings__classified') }}
    qualify row_number() over (partition by posting_key order by snapshot_date desc) = 1
)

select
    latest.posting_key,
    vocabulary.skill,
    vocabulary.category
from latest
inner join {{ ref('skill_vocabulary') }} as vocabulary
    on {{ regex_contains('latest.search_text', 'vocabulary.pattern') }}
