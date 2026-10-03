-- A posting may only be closed by a snapshot that actually succeeded for its board.
select spells.posting_spell_key, spells.closed_at
from {{ ref('fct_postings') }} as spells
left join {{ ref('stg_bronze__extract_manifests') }} as manifests
    on manifests.company_key = spells.company_key
    and manifests.snapshot_date = spells.closed_at
    and manifests.status = 'ok'
where spells.closed_at is not null and manifests.company_key is null
