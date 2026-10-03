-- All providers in one schema, deduplicated to one row per posting per snapshot.
with unioned as (
    select * from {{ ref('stg_greenhouse__postings') }}
    union all by name
    select * from {{ ref('stg_lever__postings') }}
    union all by name
    select * from {{ ref('stg_ashby__postings') }}
)

select *
from unioned
-- A provider can repeat a job inside one response; keep one deterministic copy.
qualify row_number() over (
    partition by posting_key, snapshot_date
    order by extracted_at desc, title, posting_url
) = 1
