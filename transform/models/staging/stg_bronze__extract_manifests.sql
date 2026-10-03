-- One row per (board, snapshot_date) extraction attempt, successful or not.
-- landing_id identifies one landing of a partition: extracted_at plus the content hash of
-- what was landed, so a re-landed partition with the same timestamp but different content
-- (an edited fixture, different recorded responses) still counts as changed.
select
    source,
    board,
    snapshot_date,
    source || ':' || board as company_key,
    company,
    cast(extracted_at as timestamp) as extracted_at,
    status,
    fetch_mode,
    http_status,
    attempts,
    posting_count,
    reject_count,
    url,
    error,
    coalesce(rejected_posting_ids, []) as rejected_posting_ids,
    content_hash,
    cast(cast(extracted_at as timestamp) as {{ dbt.type_string() }})
        || '#' || coalesce(content_hash, 'none') as landing_id
from {{ bronze_read('manifests', {
    'company': 'VARCHAR',
    'extracted_at': 'TIMESTAMPTZ',
    'status': 'VARCHAR',
    'fetch_mode': 'VARCHAR',
    'http_status': 'INTEGER',
    'attempts': 'INTEGER',
    'posting_count': 'INTEGER',
    'reject_count': 'INTEGER',
    'url': 'VARCHAR',
    'error': 'VARCHAR',
    'rejected_posting_ids': 'VARCHAR[]',
    'content_hash': 'VARCHAR',
}) }}
