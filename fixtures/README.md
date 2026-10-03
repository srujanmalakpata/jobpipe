# jobpipe fixtures (synthetic)

`responses/<snapshot_date>/<source>/<board>.json` are **invented** API responses shaped
like the public Greenhouse, Lever and Ashby job-board APIs. No company, posting, ID or URL
here is real, and nothing was scraped. `<board>.status` files make the fixture transport
answer with that HTTP status (used to simulate an outage).

They are generated deterministically by `scripts/generate_fixtures.py`; the scripted edge
cases the tests rely on are listed in that script's docstring. Regenerate with
`uv run python scripts/generate_fixtures.py`.
