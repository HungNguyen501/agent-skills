---
name: optimizing-databricks-cost
description: Guides finding and reducing Databricks spend. Attributes DBU cost by product, job, warehouse and user, identifies the dominant driver, maps it to a concrete lever (serverless compute, warehouse sizing and auto-stop, streaming triggers, table layout and predictive optimization, budgets and alerts), and verifies the saving afterwards. Use when asked to cut, explain a rise in, or optimize Databricks cost or performance per dollar. Not for plain cost lookups such as "how much did X cost" (use system-tables-semantic) and not for applying the changes without confirmation.
metadata:
  always: "false"
  order: "20"
---

# Optimizing Databricks cost

Work from the biggest driver down. Do not recommend a lever until the spend is attributed. Cost figures are list-price estimates, not invoices.

```
- [ ] 1. Attribute: where does the spend go, and what changed?
- [ ] 2. Name the dominant driver (product, then job / warehouse / user)
- [ ] 3. Pick the lever for that driver (table below)
- [ ] 4. Estimate the saving and state the assumptions
- [ ] 5. Propose the change and get confirmation before touching anything
- [ ] 6. Verify next period with the same query
```

## 1. Attribute

Use the semantic cost view, with the scope and 180-day filters from `system-tables-filters`. Raw billing tables are for edge cases only (`system-tables-billing`).

Change over time, by product:
```sql
SELECT billing_origin_product,
       SUM(CASE WHEN usage_date >= CURRENT_DATE - INTERVAL 30 DAYS THEN estimated_cost_usd END) AS last_30d_usd,
       SUM(CASE WHEN usage_date <  CURRENT_DATE - INTERVAL 30 DAYS THEN estimated_cost_usd END) AS prior_30d_usd
FROM vireox_infra.semantic.vw_dbu_cost
WHERE usage_date >= CURRENT_DATE - INTERVAL 60 DAYS
GROUP BY billing_origin_product
ORDER BY last_30d_usd DESC
```

Then drill into the top product:
```sql
SELECT job_name, SUM(estimated_cost_usd) AS cost_usd, SUM(total_dbus) AS dbus
FROM vireox_infra.semantic.vw_dbu_cost
WHERE usage_date >= CURRENT_DATE - INTERVAL 30 DAYS
  AND billing_origin_product = 'JOBS'
GROUP BY job_name
ORDER BY cost_usd DESC
LIMIT 20
```
Swap `job_name` for `warehouse_id`, `run_as` or `sku_name` to drill into other products. `sku_name` shows the compute mix, for example all-purpose versus jobs compute.

## 2. Map the driver to a lever

| Driver | Check | Lever | Where the guidance is |
|---|---|---|---|
| Jobs on classic or all-purpose compute | `sku_name` contains `ALL_PURPOSE`, or a job runs on a long-lived cluster | Move eligible jobs to serverless, keep classic only for real blockers | `databricks-serverless` |
| SQL warehouse | Large size, long idle time, low query volume | Serverless, size down gradually, aggressive auto-stop. Size up if queries spill to disk | `databricks-dbsql`, `references/best-practices.md`, "Warehouse Sizing Guidance" |
| Repeated identical queries | Many runs of the same dashboards | Deterministic queries (no `NOW()` or `RAND()`) so the result cache hits | `databricks-dbsql`, "Caching Strategies" |
| Streaming (continuous) | Cluster up 24/7 for a loose SLA | Match the trigger to the SLA: scheduled `availableNow` instead of continuous | `databricks-spark-structured-streaming`, `references/trigger-and-cost-optimization.md` |
| Many small streams | One cluster per stream | Several streams per cluster | same file, "Strategy 4: Multi-Stream Clusters" |
| Slow or large scans | High bytes read, wide partition scans | Liquid clustering, predictive optimization on managed tables. Do not run manual `OPTIMIZE` or `VACUUM` where predictive optimization is available | `databricks-dbsql`, "Liquid Clustering vs Traditional Partitioning" |
| Foundation-model or gateway usage | `MODEL_SERVING` or gateway SKUs | Spend budgets and alerts | `databricks-unity-gateway`, `references/budgets.md` |
| Shared warehouse, unclear who spends | `run_as` is NULL | Per-user estimate from `vw_query_perf` duration share, labelled as an estimate | `system-tables-semantic` |

Paths above are inside the vendored `databricks-agent-skills` skills. Read the one that matches the driver and no others. If those skills are not installed in this environment, say what to look for and do not invent numbers from them.

## 3. Estimate and propose

- Give each saving as a range with its assumptions, for example "estimated 20 to 40% of this job's last-30-day cost if it moves to serverless". State the figure you used as the base.
- Rank levers by estimated saving over effort. Lead with the largest.
- Vendor claims such as "serverless is on par with or cheaper than classic in most cases" are general guidance. Test them against this job's own cost before promising a saving.

## 4. Do not apply changes unprompted

Changing compute, sizes or triggers on production workloads is a state-changing action. Present a plan and wait for confirmation. For more than one workload, list each one with its current compute, its blocker check, its estimated saving and the change, so a person can review it before anything runs.

## 5. Verify

After the change, rerun the step 1 query for the same workload over a comparable period and compare. Report the result against the estimate, including when it falls short.

## Gotchas

- `estimated_cost_usd` uses list prices. Discounts and committed-use agreements make the real invoice differ, so say so when quoting a dollar figure.
- `run_as` is NULL for shared SQL warehouses. Any per-user warehouse cost is an estimate.
- Compare equal-length periods. A 31-day month against a 28-day one looks like a rise that isn't one.
- A serverless estimate based only on past cost ignores startup behaviour and runtime changes. Check one run before moving a fleet.
- Predictive optimization applies to Unity Catalog managed tables. External tables still need manual maintenance.
- On serverless SQL warehouses, `delta.enableOptimizeWrite` and `delta.autoOptimize.autoCompact` cannot be set. They are managed automatically.
