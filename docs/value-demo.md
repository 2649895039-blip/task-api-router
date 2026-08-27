# Value Demo

This is a deterministic, offline demo. It makes no API calls and uses the sample prices in `demo_route.py`.

```bash
python demo_route.py
```

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
