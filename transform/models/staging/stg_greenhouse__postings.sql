-- Greenhouse Job Board API -> common posting schema.
-- Greenhouse has no remote/employment fields: both are inferred from location / title text.
with source_rows as (
    select * from {{ ref('stg_bronze__postings') }}
    where source = 'greenhouse'
),

parsed as (
    select
        *,
        nullif(trim({{ json_str('payload', '$.title') }}), '') as title,
        nullif(trim({{ json_str('payload', '$.location.name') }}), '') as location_raw
    from source_rows
)

select
    posting_key,
    company_key,
    source,
    board,
    company,
    posting_id,
    snapshot_date,
    extracted_at,
    title,
    {{ json_str('payload', '$.departments[0].name') }} as department,
    location_raw,
    {{ workplace_from_location('location_raw') }} as workplace_type,
    {{ normalize_employment('null', 'title') }} as employment_type,
    {{ to_utc_timestamp(json_str('payload', '$.first_published')) }} as published_at,
    {{ to_utc_timestamp(json_str('payload', '$.updated_at')) }} as updated_at,
    {{ json_str('payload', '$.absolute_url') }} as posting_url,
    {{ html_to_text(json_str('payload', '$.content')) }} as description_text
from parsed
