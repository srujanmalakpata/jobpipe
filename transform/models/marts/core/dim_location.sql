-- One row per distinct raw location string, parsed into city / region / country.
-- Region and country come from the resolve_geo macro (macros/geo.sql); its behaviour is
-- pinned by seeds/geo_location_cases.csv and tests/assert_geo_resolution_behaves.sql.
with locations as (
    select
        location_key,
        arg_max(location_raw, snapshot_date) as location_raw
    from {{ ref('int_postings__classified') }}
    group by location_key
),

geo as (
    {{ resolve_geo('locations') }}
)

select
    locations.location_key,
    locations.location_raw,
    case
        when locations.location_raw is null then null
        when lower(locations.location_raw) like 'remote%' then null
        else trim(split_part(locations.location_raw, ',', 1))
    end as city,
    geo.region,
    coalesce(geo.country, 'Unknown') as country,
    coalesce(lower(locations.location_raw) like '%remote%', false) as mentions_remote
from locations
left join geo on geo.location_key = locations.location_key
