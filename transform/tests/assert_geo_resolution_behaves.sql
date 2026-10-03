-- Every example in geo_location_cases must resolve to the stated region and country
-- (empty = NULL region; country 'Unknown' when nothing matched, as in dim_location).
with cases as (
    select location_raw as location_key, location_raw, region, country
    from {{ ref('geo_location_cases') }}
),

resolved as (
    {{ resolve_geo('cases') }}
)

select
    cases.location_raw,
    cases.region as expected_region,
    resolved.region as actual_region,
    cases.country as expected_country,
    coalesce(resolved.country, 'Unknown') as actual_country
from cases
left join resolved on resolved.location_key = cases.location_key
where resolved.region is distinct from cases.region
   or coalesce(resolved.country, 'Unknown') is distinct from cases.country
