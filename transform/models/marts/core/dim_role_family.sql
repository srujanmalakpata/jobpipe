-- Role families come from a seed so analysts can edit them without touching SQL.
select
    role_family,
    display_name,
    archetype
from {{ ref('role_families') }}
