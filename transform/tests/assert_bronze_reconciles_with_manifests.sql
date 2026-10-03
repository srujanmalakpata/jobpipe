-- Reconciliation: lines in each bronze postings partition = the manifest's posting_count,
-- and every postings partition has an ok manifest.
with lines as (
    select company_key, snapshot_date, count(*) as landed
    from {{ ref('stg_bronze__postings') }}
    group by company_key, snapshot_date
)

select
    coalesce(lines.company_key, manifests.company_key) as company_key,
    coalesce(lines.snapshot_date, manifests.snapshot_date) as snapshot_date,
    lines.landed,
    manifests.posting_count,
    manifests.status
from lines
full outer join {{ ref('stg_bronze__extract_manifests') }} as manifests
    on manifests.company_key = lines.company_key
    and manifests.snapshot_date = lines.snapshot_date
where (lines.landed is not null and coalesce(manifests.status, 'missing') <> 'ok')
   or (manifests.status = 'ok' and coalesce(lines.landed, 0) <> manifests.posting_count)
