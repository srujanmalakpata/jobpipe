-- An open spell must have been seen on its board's latest successful snapshot.
with latest as (
    select company_key, max(snapshot_date) as latest_ok
    from {{ ref('stg_bronze__extract_manifests') }}
    where status = 'ok'
    group by company_key
)

select spells.posting_spell_key, spells.last_seen, latest.latest_ok
from {{ ref('fct_postings') }} as spells
inner join latest on latest.company_key = spells.company_key
where spells.is_open and spells.last_seen <> latest.latest_ok
