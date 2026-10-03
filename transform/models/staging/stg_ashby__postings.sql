-- Ashby public job-board API -> common posting schema. Unlisted jobs are dropped here.
with source_rows as (
    select * from {{ ref('stg_bronze__postings') }}
    where source = 'ashby'
),

parsed as (
    select
        *,
        nullif(trim({{ json_str('payload', '$.title') }}), '') as title,
        nullif(trim({{ json_str('payload', '$.location') }}), '') as location_raw,
        lower({{ json_str('payload', '$.workplaceType') }}) as ashby_workplace,
        cast({{ json_str('payload', '$.isRemote') }} as boolean) as ashby_is_remote,
        coalesce(cast({{ json_str('payload', '$.isListed') }} as boolean), true) as is_listed
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
    {{ json_str('payload', '$.department') }} as department,
    location_raw,
    case
        when ashby_workplace = 'remote' or ashby_is_remote then 'remote'
        when ashby_workplace = 'hybrid' then 'hybrid'
        when ashby_workplace = 'onsite' then 'onsite'
        else {{ workplace_from_location('location_raw') }}
    end as workplace_type,
    {{ normalize_employment(json_str('payload', '$.employmentType'), 'title') }}
        as employment_type,
    {{ to_utc_timestamp(json_str('payload', '$.publishedAt')) }} as published_at,
    cast(null as timestamp) as updated_at,
    {{ json_str('payload', '$.jobUrl') }} as posting_url,
    coalesce(
        nullif(trim({{ json_str('payload', '$.descriptionPlain') }}), ''),
        {{ html_to_text(json_str('payload', '$.descriptionHtml')) }}
    ) as description_text
from parsed
where is_listed
