{#- HTML -> plain text, good enough for keyword search (not a general HTML parser).
    Entities are decoded twice because Greenhouse double-escapes its `content` field:
    `&lt;p&gt;` -> `<p>` (tags stripped) and `&amp;amp;` -> `&amp;` -> `&`. -#}
{% macro decode_entities(expr) -%}
replace(replace(replace(replace(replace(replace(
    {{ expr }}, '&lt;', '<'), '&gt;', '>'), '&quot;', '"'), '&#39;', ''''), '&nbsp;', ' '), '&amp;', '&')
{%- endmacro %}

{% macro html_to_text(expr) -%}
nullif(trim(regexp_replace(
    {{ decode_entities("regexp_replace(" ~ decode_entities(expr) ~ ", '<[^>]+>', ' ', 'g')") }},
    '\s+', ' ', 'g')), '')
{%- endmacro %}

{#- Remote / hybrid / onsite from free-text location when the provider has no field. -#}
{% macro workplace_from_location(location) -%}
case
    when {{ location }} is null or trim({{ location }}) = '' then 'unknown'
    when lower({{ location }}) like '%remote%' then 'remote'
    when lower({{ location }}) like '%hybrid%' then 'hybrid'
    else 'onsite'
end
{%- endmacro %}

{#- Provider employment labels ("Full-time", "FullTime", "Intern", ...) -> one vocabulary. -#}
{% macro normalize_employment(label, title) -%}
case
    when {{ regex_contains("lower(coalesce(" ~ label ~ ", ''))", "'intern|co-?op'") }} then 'internship'
    when {{ regex_contains("lower(coalesce(" ~ label ~ ", ''))", "'part'") }} then 'part_time'
    when {{ regex_contains("lower(coalesce(" ~ label ~ ", ''))", "'contract|temporary|fixed'") }} then 'contract'
    when {{ regex_contains("lower(coalesce(" ~ label ~ ", ''))", "'full'") }} then 'full_time'
    when {{ regex_contains("lower(coalesce(" ~ title ~ ", ''))", "'\\b(intern|internship|co-?op)\\b'") }} then 'internship'
    else 'unknown'
end
{%- endmacro %}

{#- Seniority from the job title. Order matters: the most senior signal wins, so
    "Senior Associate" is senior and "Associate Director" is staff_plus, not entry.
    "Associate" alone (Associate Software Engineer, Associate Product Manager) is entry,
    except legal titles such as "Associate General Counsel". Examples with expected results
    live in seeds/title_classification_cases.csv. -#}
{% macro classify_seniority(title, employment_type) -%}
case
    when {{ employment_type }} = 'internship'
      or {{ regex_contains("lower(" ~ title ~ ")", "'\\b(intern|internship|co-?op)\\b'") }} then 'intern'
    when {{ regex_contains("lower(" ~ title ~ ")", "'\\b(staff|principal|distinguished|director|head of|vp|vice president|chief)\\b'") }} then 'staff_plus'
    when {{ regex_contains("lower(" ~ title ~ ")", "'\\b(senior|sr|lead)\\b'") }} then 'senior'
    when {{ regex_contains("lower(" ~ title ~ ")", "'\\b(junior|jr|new grad|new graduate|graduate|entry[- ]level)\\b'") }} then 'entry'
    when {{ regex_contains("lower(" ~ title ~ ")", "'\\bassociate\\b'") }}
      and not {{ regex_contains("lower(" ~ title ~ ")", "'\\bassociate (general )?counsel\\b'") }} then 'entry'
    else 'mid'
end
{%- endmacro %}
