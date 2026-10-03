{#-
  Posting lifecycle, SCD2-style: one row per *spell* - a maximal run of consecutive
  successful board snapshots in which the posting was listed.

    first_seen  first snapshot of the spell
    last_seen   last snapshot of the spell
    closed_at   the next successful snapshot of that board (posting absent), else NULL

  Only status='ok' snapshots count, so a failed fetch can never close a posting. A posting
  that was listed but failed the extract contract that day (a quarantined reject) still
  counts as observed, so a one-off bad record does not close and reopen it. A posting that
  disappears and comes back gets a second spell (spell_number = 2).

  Incremental: a board is recomputed (delete+insert on company_key) only when its set of
  successful snapshots changed, detected by a watermark hash over (snapshot_date,
  landing_id), where landing_id = extracted_at + the content hash of the landed partition.
  That also handles late-arriving / backfilled days, re-landed days whose content changed
  under the same timestamp, and days invalidated with `pipeline invalidate`. The pre-hook
  deletes the old spells of every changed board first, so a board that now yields zero
  spells does not keep stale rows.
-#}
{{ config(
    materialized='incremental',
    unique_key='company_key',
    incremental_strategy='delete+insert',
    on_schema_change='fail',
    pre_hook="{{ delete_stale_board_spells() }}",
) }}

with board_snapshots as (
    select
        company_key,
        snapshot_date,
        row_number() over (partition by company_key order by snapshot_date) as snapshot_seq,
        min(snapshot_date) over (partition by company_key) as board_first_snapshot
    from {{ ref('stg_bronze__extract_manifests') }}
    where status = 'ok'
),

board_watermarks as (
    {{ ok_board_watermarks() }}
),

changed_boards as (
    select board_watermarks.*
    from board_watermarks
    {% if is_incremental() %}
    where not exists (
        select 1 from {{ this }} as loaded
        where loaded.company_key = board_watermarks.company_key
            and loaded.board_watermark = board_watermarks.board_watermark
    )
    {% endif %}
),

parsed_observations as (
    select posting_key, company_key, snapshot_date, true as is_parsed
    from {{ ref('fct_posting_daily') }}
    where company_key in (select company_key from changed_boards)
),

-- Listed but rejected by the extract contract: still evidence the posting was open that
-- day. Only postings we have parsed at least once on this board can be placed in a spell.
unparsed_observations as (
    select unparsed.posting_key, unparsed.company_key, unparsed.snapshot_date, false as is_parsed
    from {{ ref('stg_bronze__unparsed_postings') }} as unparsed
    where unparsed.company_key in (select company_key from changed_boards)
        and unparsed.posting_key in (select posting_key from parsed_observations)
        and not exists (
            select 1 from parsed_observations as parsed
            where parsed.posting_key = unparsed.posting_key
                and parsed.snapshot_date = unparsed.snapshot_date
        )
),

observations as (
    select
        all_observations.*,
        board_snapshots.snapshot_seq
    from (
        select * from parsed_observations
        union all
        select * from unparsed_observations
    ) as all_observations
    inner join board_snapshots
        on board_snapshots.company_key = all_observations.company_key
        and board_snapshots.snapshot_date = all_observations.snapshot_date
),

-- Gaps-and-islands: consecutive snapshot_seq values share the same (seq - row_number).
islands as (
    select
        *,
        snapshot_seq - row_number() over (
            partition by posting_key order by snapshot_seq
        ) as island_id
    from observations
),

spells as (
    select
        posting_key,
        company_key,
        island_id,
        min(snapshot_date) as first_seen,
        max(snapshot_date) as last_seen,
        max(snapshot_date) filter (where is_parsed) as last_parsed_seen,
        max(snapshot_seq) as last_seq,
        count(*) as snapshots_observed,
        count(*) filter (where not is_parsed) as unparsed_snapshots
    from islands
    group by posting_key, company_key, island_id
    -- an island made only of rejected records has no attributes to report
    having count(*) filter (where is_parsed) > 0
)

select
    spells.posting_key || '@' || cast(spells.first_seen as {{ dbt.type_string() }})
        as posting_spell_key,
    spells.posting_key,
    spells.company_key,
    row_number() over (partition by spells.posting_key order by spells.first_seen)
        as spell_number,
    spells.first_seen,
    spells.last_seen,
    next_snapshot.snapshot_date as closed_at,
    next_snapshot.snapshot_date is null as is_open,
    spells.first_seen = first_snapshot.board_first_snapshot as is_left_censored,
    spells.snapshots_observed,
    spells.unparsed_snapshots,
    {{ days_between('spells.first_seen', 'next_snapshot.snapshot_date') }} as days_to_close,
    -- attributes as of the spell's last parsed observation (titles can change mid-spell)
    latest.title,
    latest.role_family,
    latest.seniority,
    latest.is_entry_level,
    latest.employment_type,
    latest.workplace_type,
    latest.location_key,
    latest.published_at,
    changed_boards.board_watermark
from spells
inner join changed_boards
    on changed_boards.company_key = spells.company_key
inner join (
    select distinct company_key, board_first_snapshot from board_snapshots
) as first_snapshot
    on first_snapshot.company_key = spells.company_key
left join board_snapshots as next_snapshot
    on next_snapshot.company_key = spells.company_key
    and next_snapshot.snapshot_seq = spells.last_seq + 1
inner join {{ ref('fct_posting_daily') }} as latest
    on latest.posting_key = spells.posting_key
    and latest.snapshot_date = spells.last_parsed_seen
