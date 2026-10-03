{#- Fails for rows where the column falls outside [min_value, max_value]. -#}
{% test between(model, column_name, min_value, max_value) %}
select *
from {{ model }}
where {{ column_name }} < {{ min_value }} or {{ column_name }} > {{ max_value }}
{% endtest %}
