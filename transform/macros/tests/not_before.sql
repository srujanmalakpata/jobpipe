{#- Fails for rows where `column_name` is earlier than `reference` (or not strictly later
    when strict=true). NULLs in either column are ignored. -#}
{% test not_before(model, column_name, reference, strict=false) %}
select *
from {{ model }}
where {{ column_name }} is not null
  and {{ reference }} is not null
  and {{ column_name }} {{ '<=' if strict else '<' }} {{ reference }}
{% endtest %}
