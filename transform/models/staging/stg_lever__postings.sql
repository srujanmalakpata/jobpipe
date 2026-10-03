-- Lever Postings API -> common posting schema.
-- Lever splits the description across descriptionPlain, lists[].content (HTML) and
-- additionalPlain; all three are searched for skills.
with source_rows as (
    select * from {{ ref('stg_bronze__postings') }}
    where source = 'lever'
),

parsed as (
    select
        *,
        nullif(trim({{ json_str('payload', '$.text') }}), '') as title,
        nullif(trim({{ json_str('payload', '$.categories.location') }}), '') as location_raw,
        lower({{ json_str('payload', '$.workplaceType') }}) as lever_workplace,
        array_to_string(json_extract_string(payload, '$.lists[*].content'), ' ') as lists_html
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
    coalesce(
        {{ json_str('payload', '$.categories.department') }},
        {{ json_str('payload', '$.categories.team') }}
    ) as department,
    location_raw,
    case lever_workplace
        when 'remote' then 'remote'
        when 'hybrid' then 'hybrid'
        when 'on-site' then 'onsite'
        else {{ workplace_from_location('location_raw') }}
    end as workplace_type,
    {{ normalize_employment(json_str('payload', '$.categories.commitment'), 'title') }}
        as employment_type,
    epoch_ms(cast({{ json_str('payload', '$.createdAt') }} as bigint)) as published_at,
    cast(null as timestamp) as updated_at,
    {{ json_str('payload', '$.hostedUrl') }} as posting_url,
    {{ html_to_text(
        "concat_ws(' ', " ~ json_str('payload', '$.descriptionPlain') ~ ", lists_html, "
        ~ json_str('payload', '$.additionalPlain') ~ ")"
    ) }} as description_text
from parsed
