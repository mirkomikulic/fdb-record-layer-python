# Contributing

Thanks for your interest in improving FDB Record Layer for Python. Bug reports,
fixes, documentation and new features are all welcome.

## Before you start

- For bugs, open an issue with a minimal reproduction, your Python, `protobuf`,
  `foundationdb` and FoundationDB server versions.
- For larger changes or new features, open an issue first so we can agree on
  the approach before you spend time on it.
- Behaviour should match the [Java Record Layer](https://github.com/FoundationDB/fdb-record-layer)
  where it makes sense; mention it in the PR when you deliberately diverge.

## Development setup

```bash
git clone https://github.com/mirkomikulic/fdb-record-layer-python
cd fdb-record-layer-python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,sql]"
```

Unit tests don't need FoundationDB:

```bash
pytest
```

Integration tests and examples need a local FoundationDB (Docker) and a client
library with the same major.minor version. See
[README → Local FoundationDB](README.md#local-foundationdb).

## Before opening a pull request

Run the same checks as CI:

```bash
ruff check fdb_record_layer tests examples/quickstart.py
ruff format fdb_record_layer tests examples/quickstart.py
mypy fdb_record_layer
pytest
```

- Add or update tests for your change. Bug fixes should include a test that
  fails without the fix.
- If you change a public API, update the README and `examples/quickstart.py`
  (CI runs it against a real FoundationDB).
- Add a line to the `[Unreleased]` section of [CHANGELOG.md](CHANGELOG.md).
- Keep pull requests focused on one change.

## Releases

Maintainers release by bumping `version` in `pyproject.toml` and
`__version__` in `fdb_record_layer/__init__.py`, moving the changelog entries
under the new version, and pushing a `v<version>` tag. The release workflow
checks that the tag matches the package version, publishes to TestPyPI and PyPI
and creates the GitHub release.

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). By
participating you agree to uphold it.

## License

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE).
