-- One row per posting line landed in bronze (duplicates within a response are kept here).
select
    source,
    board,
    snapshot_date,
    company,
    cast(extracted_at as timestamp) as extracted_at,
    posting_id,
    payload,
    source || ':' || board as company_key,
    source || ':' || board || ':' || posting_id as posting_key
from {{ bronze_read('postings', {
    'company': 'VARCHAR',
    'extracted_at': 'TIMESTAMPTZ',
    'posting_id': 'VARCHAR',
    'payload': 'JSON',
}) }}
