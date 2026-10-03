{#-
  Resolve free-text locations to (region, country) with the geo_aliases seed.

  `locations` names a relation or CTE with columns location_key and location_raw. The raw
  string is split on , ; ( ) / | - and every segment is matched exactly against the seed
  aliases (kind = region | country | city). Precedence:

  1. A named country ("India", "United Kingdom") decides the country.
  2. A region code ("ON", "TX") decides the region and country, unless it conflicts with
     a named country, or the code is also the ISO country code of the city found in the
     same string: "Toronto, CA" and "Bengaluru, IN" use CA / IN as country codes (Canada,
     India), while "San Francisco, CA" and "London, ON" keep California / Ontario.
  3. Otherwise a known city decides both ("Toronto" -> Ontario, Canada).

  A bare ambiguous code with no known city ("Pune, IN") still reads as a US state; those
  cases are listed in seeds/geo_location_cases.csv with the behaviour they get.
-#}
{% macro resolve_geo(locations) -%}
with geo_split as (
    select
        location_key,
        string_split_regex(lower(coalesce(location_raw, '')), '[,;()/|-]') as parts
    from {{ locations }}
),

geo_tokens as (
    select
        geo_split.location_key,
        position,
        trim(geo_split.parts[position]) as token
    from geo_split, range(1, len(geo_split.parts) + 1) as positions(position)
),

geo_found as (
    -- the first (leftmost) alias of each kind in the string
    select
        geo_tokens.location_key,
        arg_min(aliases.country, geo_tokens.position)
            filter (where aliases.kind = 'country') as named_country,
        arg_min(aliases.region, geo_tokens.position)
            filter (where aliases.kind = 'region') as code_region,
        arg_min(aliases.country, geo_tokens.position)
            filter (where aliases.kind = 'region') as code_country,
        arg_min(aliases.also_country, geo_tokens.position)
            filter (where aliases.kind = 'region') as code_also_country,
        arg_min(nullif(aliases.region, ''), geo_tokens.position)
            filter (where aliases.kind = 'city') as city_region,
        arg_min(aliases.country, geo_tokens.position)
            filter (where aliases.kind = 'city') as city_country
    from geo_tokens
    inner join {{ ref('geo_aliases') }} as aliases on aliases.alias = geo_tokens.token
    group by geo_tokens.location_key
),

geo_judged as (
    select
        *,
        code_region is not null
            and coalesce(code_country = named_country, named_country is null)
            and not coalesce(code_also_country = city_country, false) as code_is_region
    from geo_found
),

geo_resolved as (
    select
        location_key,
        coalesce(
            named_country,
            case when code_is_region then code_country end,
            city_country,
            code_also_country
        ) as country,
        case when code_is_region then code_region end as code_region,
        city_region,
        city_country
    from geo_judged
)

select
    location_key,
    coalesce(code_region, case when city_country = country then city_region end) as region,
    country
from geo_resolved
{%- endmacro %}
