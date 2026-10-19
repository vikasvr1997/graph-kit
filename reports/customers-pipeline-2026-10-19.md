# Customers_data → Spanner validation — 2026-10-19

Project: `premium-odyssey-508202-k9`; region: `us-east1`. Source: BigQuery `Customers_data`. Destination: Spanner `graphkit-benchmark/customers_serving`.

Native BigQuery `EXPORT DATA` performed all writes. Cloud Workflows coordinated validation and exports; Terraform deployed the schema, IAM, workflow, scheduler and monitoring. No new BigQuery reservation or paid Spanner instance was created.

## Initial load

- Workflow execution: `5c0bf02b-09d6-49aa-bad5-88c6d343b1e6`.
- Source snapshot: `2026-10-19T15:40:18.595229Z`.
- Duration: **149.26 seconds** (2 minutes 29 seconds).
- **13 tables, 549,586 rows** copied.
- All row counts, per-column null counts, numeric sums, string length sums and five ordered sample rows per table matched. These checks do not establish equality of every cell.
- Source keys passed null, duplicate and length checks before any export.
- Two preliminary executions failed during new service-account authentication, before acquiring the lock or writing rows. After IAM propagation, the full load succeeded. The Monitoring alert also required retrying after log-metric propagation.

| BigQuery table | Spanner table | Rows | Aggregate/sample checks |
|---|---|---:|---|
| `customer_data` | `customers` | 200 | Pass |
| `drivers` | `drivers` | 150 | Pass |
| `facilities` | `facilities` | 50 | Pass |
| `routes` | `routes` | 58 | Pass |
| `trailers` | `trailers` | 180 | Pass |
| `loads` | `loads` | 85,410 | Pass |
| `trips` | `trips` | 85,410 | Pass |
| `daily-events` | `events` | 170,820 | Pass |
| `fuel_purchases` | `fuel_purchases` | 196,442 | Pass |
| `maintanance-records` | `maintenance_records` | 2,920 | Pass |
| `safety-incidents` | `safety_incidents` | 170 | Pass |
| `delivery-monthly-metrics` | `delivery_monthly_metrics` | 4,464 | Pass |
| `truck-utilization-metrics` | `truck_utilization_metrics` | 3,312 | Pass |

## Hourly trigger and repeat load

- Cloud Scheduler is **ENABLED** with `0 * * * *`, timezone `America/Detroit`.
- A manual execution of the Scheduler job successfully invoked Workflows through its dedicated service account.
- Scheduler-triggered execution: `724f2867-e795-4caa-b1aa-0a6a4b0eb9b4`, **SUCCEEDED** in **157.87 seconds**.
- Repeat validation passed for all 13 tables and 549,586 rows. Counts stayed unchanged, and all aggregate/sample checks matched the second run's source snapshot; no duplicate rows were introduced.
- Terraform validation passed; the final plan found no infrastructure differences. All **54 offline tests passed**.

## Operating boundaries

Hourly full-table upserts do not propagate source hard deletes. The source timestamp is consistent across all exports; destination publication is table-by-table. Failures retain a lock for operator inspection. Monitoring has no notification channels. The existing free-trial Spanner instance expires on 2027-01-17.

See [deployment and operations](../pipelines/customers_to_spanner/README.md) and [Google native export documentation](https://docs.cloud.google.com/bigquery/docs/export-to-spanner). The custom pipeline has no separate Google certification.
