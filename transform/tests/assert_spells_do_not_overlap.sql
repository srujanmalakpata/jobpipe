-- Two spells of the same posting must not overlap in time.
select a.posting_spell_key, b.posting_spell_key as overlapping_spell_key
from {{ ref('fct_postings') }} as a
inner join {{ ref('fct_postings') }} as b
    on a.posting_key = b.posting_key
    and a.posting_spell_key < b.posting_spell_key
where a.first_seen <= b.last_seen and b.first_seen <= a.last_seen
