# Value Demo

This is a deterministic, offline demo. It makes no API calls and uses the sample prices in `demo_route.py`.

```bash
python demo_route.py
```

For a machine-readable five-task cost comparison, run `python benchmark_route.py`.
It writes `benchmark-report.json` and makes no provider calls. The numbers are
fixed illustrative fixtures, not a production savings claim.

It demonstrates three decisions:

1. A debugging task goes to the stronger reasoning model.
2. A bulk translation task goes to the lower-cost model.
3. A destructive repository action is blocked locally before execution.

The final section compares the routed estimate with an "always use the strongest model" baseline. This is an illustrative signal, not a promise of fixed savings; actual savings depend on your model prices and workload.

## What makes this different

Most model gateways route requests by endpoint, key, or a fixed fallback chain. This project routes one user task at a time using capability labels and a ranking file, while only selecting models that the user has configured.

The practical tradeoff is explicit:

| Approach | Decision unit | User controls | Built-in local safety |
| --- | --- | --- | --- |
| Fixed provider proxy | Request | Endpoint/provider | Usually separate |
| Task API Router | Task | Models, rankings, costs | Action guard hook |

The router is intentionally local-first: common task types are classified without an extra model call, and ambiguous tasks can use one short classification call before execution.

## Try routing without spending

After install, preview the route decision offline:

```bash
task-router --route "写一个 Python 函数解析 JSON"
task-router --route "批量翻译以下 50 条产品标题" --json
```

This uses only local keywords and the ranking file. It never calls a provider. After real runs, `task-router --stats` summarizes local `history.jsonl` cost and model distribution (baseline comparison is illustrative, not a savings promise).
