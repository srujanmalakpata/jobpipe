# jobpipe report

Data from **5 boards**, snapshots **2026-08-03** to **2026-09-07** (fetch mode: fixture).

- Distinct postings: 115 (116 listing spells, 68 open at the latest snapshot)
- Board snapshots: 29 ok, 1 failed; extract-contract rejects: 2

> Fixture mode: every company and posting in this report is synthetic.

## Extraction health by board

_Failed snapshots never close postings; contract rejects are quarantined in bronze._

| company_name | source | board | ok_snapshots | failed_snapshots | rejected_records | postings_seen |
|---|---|---|---|---|---|---|
| Aurora Health Labs | lever | auroralabs | 6 | 0 | 1 | 24 |
| Glacier Games | ashby | glaciergames | 6 | 0 | 1 | 22 |
| Maple Ledger | greenhouse | mapleledger | 6 | 0 | 0 | 21 |
| Northwind Robotics | greenhouse | northwindrobotics | 6 | 0 | 0 | 23 |
| Tidewater Logistics | lever | tidewaterlogistics | 5 | 1 | 0 | 25 |

## Postings opened and closed per week

_The first week opens nothing by construction: postings already listed when observation began are left-censored._

| week_start | boards_observed | listed_postings | opened | reopened | closed | net_change |
|---|---|---|---|---|---|---|
| 2026-08-03 | 5 | 52 | 0 | 0 | 0 | 0 |
| 2026-08-10 | 5 | 59 | 15 | 0 | 8 | 7 |
| 2026-08-17 | 5 | 64 | 11 | 0 | 6 | 5 |
| 2026-08-24 | 4 | 51 | 8 | 0 | 7 | 1 |
| 2026-08-31 | 5 | 71 | 17 | 1 | 10 | 7 |
| 2026-09-07 | 5 | 68 | 13 | 0 | 17 | -4 |

## Time to close (days, snapshot resolution)

_Measured first_seen -> closed_at. Still-open spells are right-censored, so these figures understate how long the longest-lived postings stay up._

| role_family | closed_spells | still_open_spells | median_days_to_close | mean_days_to_close | p75_days_to_close |
|---|---|---|---|---|---|
| all_roles | 14 | 68 | 14.0 | 15.5 | 21.0 |
| software_engineering | 5 | 17 | 14.0 | 12.6 | 14.0 |
| data_engineering | 3 | 6 | 14.0 | 16.3 | 21.0 |
| data_analytics | 2 | 15 | 17.5 | 17.5 | 19.2 |
| sales_business | 2 | 4 | 24.5 | 24.5 | 26.2 |
| data_science_ml | 1 | 7 | 7.0 | 7.0 | 7.0 |
| devops_infra | 1 | 3 | 14.0 | 14.0 | 14.0 |
| design | 0 | 6 | - | - | - |
| embedded_hardware | 0 | 5 | - | - | - |
| qa_test | 0 | 4 | - | - | - |
| security | 0 | 1 | - | - | - |

## Top skills across all postings

_Keyword matches against the seed vocabulary (transform/seeds/skill_vocabulary.csv)._

| skill | category | postings_with_skill | share_of_postings | open_with_skill | share_of_open |
|---|---|---|---|---|---|
| Python | language | 38 | 33.0% | 25 | 36.8% |
| SQL | language | 23 | 20.0% | 12 | 17.6% |
| Git | tool | 18 | 15.7% | 11 | 16.2% |
| Linux | devops | 16 | 13.9% | 9 | 13.2% |
| Excel | analytics | 15 | 13.0% | 10 | 14.7% |
| BigQuery | data | 14 | 12.2% | 8 | 11.8% |
| C++ | language | 14 | 12.2% | 9 | 13.2% |
| dbt | data | 13 | 11.3% | 9 | 13.2% |
| Tableau | analytics | 12 | 10.4% | 7 | 10.3% |
| CI/CD | devops | 11 | 9.6% | 5 | 7.3% |
| Statistics | analytics | 11 | 9.6% | 8 | 11.8% |
| AWS | cloud | 10 | 8.7% | 6 | 8.8% |
| Accessibility | design | 10 | 8.7% | 6 | 8.8% |
| Kubernetes | devops | 10 | 8.7% | 5 | 7.3% |
| Power BI | analytics | 10 | 8.7% | 6 | 8.8% |

## Top 3 skills per role family

| role_family | rank_in_family | skill | postings_with_skill | share_of_postings |
|---|---|---|---|---|
| data_analytics | 1 | Python | 13 | 56.5% |
| data_analytics | 2 | Tableau | 12 | 52.2% |
| data_analytics | 3 | Power BI | 10 | 43.5% |
| data_engineering | 1 | BigQuery | 5 | 45.5% |
| data_engineering | 1 | SQL | 5 | 45.5% |
| data_engineering | 1 | dbt | 5 | 45.5% |
| data_science_ml | 1 | Machine learning | 8 | 66.7% |
| data_science_ml | 2 | TensorFlow | 6 | 50.0% |
| data_science_ml | 3 | AWS | 5 | 41.7% |
| data_science_ml | 3 | Kubernetes | 5 | 41.7% |
| data_science_ml | 3 | PyTorch | 5 | 41.7% |
| data_science_ml | 3 | pandas | 5 | 41.7% |
| data_science_ml | 3 | scikit-learn | 5 | 41.7% |
| design | 1 | Accessibility | 8 | 100.0% |
| design | 2 | Figma | 7 | 87.5% |
| devops_infra | 1 | Azure | 4 | 66.7% |
| devops_infra | 2 | Go | 3 | 50.0% |
| devops_infra | 2 | Grafana | 3 | 50.0% |
| embedded_hardware | 1 | Linux | 7 | 100.0% |
| embedded_hardware | 2 | C++ | 6 | 85.7% |
| embedded_hardware | 3 | C | 5 | 71.4% |
| embedded_hardware | 3 | Git | 5 | 71.4% |
| qa_test | 1 | Playwright | 6 | 85.7% |
| qa_test | 2 | CI/CD | 5 | 71.4% |
| qa_test | 2 | JavaScript | 5 | 71.4% |
| qa_test | 2 | Python | 5 | 71.4% |
| sales_business | 1 | Excel | 8 | 100.0% |
| sales_business | 2 | SQL | 7 | 87.5% |
| sales_business | 2 | Salesforce | 7 | 87.5% |
| security | 1 | Linux | 2 | 100.0% |
| security | 2 | Go | 1 | 50.0% |
| security | 2 | Kubernetes | 1 | 50.0% |
| software_engineering | 1 | Git | 13 | 41.9% |
| software_engineering | 2 | Python | 11 | 35.5% |
| software_engineering | 3 | C# | 8 | 25.8% |
| software_engineering | 3 | C++ | 8 | 25.8% |
| software_engineering | 3 | REST API | 8 | 25.8% |
| software_engineering | 3 | Unity | 8 | 25.8% |

## Remote share of listed postings

| week_start | listed_postings | remote_postings | hybrid_postings | onsite_postings | remote_share | hybrid_share |
|---|---|---|---|---|---|---|
| 2026-08-03 | 52 | 12 | 5 | 35 | 23.1% | 9.6% |
| 2026-08-10 | 59 | 16 | 3 | 40 | 27.1% | 5.1% |
| 2026-08-17 | 64 | 21 | 5 | 38 | 32.8% | 7.8% |
| 2026-08-24 | 51 | 18 | 3 | 30 | 35.3% | 5.9% |
| 2026-08-31 | 71 | 23 | 4 | 44 | 32.4% | 5.6% |
| 2026-09-07 | 68 | 21 | 5 | 42 | 30.9% | 7.3% |

## Entry-level share of listed postings (interns, co-ops, junior, new grad)

| week_start | listed_postings | intern_postings | entry_level_postings | entry_level_share |
|---|---|---|---|---|
| 2026-08-03 | 52 | 7 | 9 | 17.3% |
| 2026-08-10 | 59 | 7 | 11 | 18.6% |
| 2026-08-17 | 64 | 11 | 16 | 25.0% |
| 2026-08-24 | 51 | 8 | 12 | 23.5% |
| 2026-08-31 | 71 | 13 | 24 | 33.8% |
| 2026-09-07 | 68 | 14 | 25 | 36.8% |
