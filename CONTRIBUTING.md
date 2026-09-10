# Contributing

Thanks for helping improve **task-api-router**.

## Ground rules

- Keep API keys, local `config/models.yaml`, and `data/` out of commits.
- Prefer offline tests. Do not add live provider calls to the unit suite.
- Do not invent savings claims. Demo numbers must stay labeled illustrative.
- Keep the routing core free of provider-specific brand names; it only uses `model_id`.

## Development setup

```bash
git clone https://github.com/2649895039-blip/task-api-router.git
cd task-api-router
python -m pip install -e .
python -m unittest tests.test_routing -v
python scripts/verify_release.py
```

Optional offline checks:

```bash
python demo_route.py
python benchmark_route.py
python -m task_router --doctor
python -m task_router --route "写一个 Python 函数解析 JSON"
```

## Pull requests

1. Open an issue first for larger behavior changes.
2. Add or update tests for every behavior change.
3. Run the full unit suite and `scripts/verify_release.py`.
4. Keep commits focused and explain the *why* in the PR body.
5. Update `CHANGELOG.md` and version metadata together when releasing.

## Good first contributions

- New keyword coverage in `task_router/preclassify.py` (with tests)
- Additional destructive patterns in `task_router/action_guard.py` (with tests)
- Provider example snippets in `config/models.example.yaml`
- README clarifications from real install friction

## Releasing

Version lives in three places and must match:

- `task_router/__init__.py` (`__version__`)
- `pyproject.toml`
- `.claude-plugin/plugin.json`

Tag `vX.Y.Z` after tests are green; the release workflow builds artifacts automatically.

## Code of conduct

Be specific, kind, and evidence-based. Report bugs with reproduction steps.
Do not spam issues, stars, or community channels.
