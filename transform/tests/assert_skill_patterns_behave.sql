-- Every documented example in skill_pattern_cases must behave as stated.
select cases.text, cases.skill, cases.should_match
from {{ ref('skill_pattern_cases') }} as cases
inner join {{ ref('skill_vocabulary') }} as vocabulary on vocabulary.skill = cases.skill
where {{ regex_contains('lower(cases.text)', 'vocabulary.pattern') }} <> cases.should_match
