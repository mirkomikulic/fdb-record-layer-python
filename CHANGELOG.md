# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/) (with PEP 440 pre-release numbers).

## [Unreleased]

## [0.1.0b8] - 2026-11-25

### Fixed
- Repeated-field detection (`field(...)`, `nest(...)`) crashed with `AttributeError`
  on protobuf 7, which removed `FieldDescriptor.label`. Schema evolution checks
  silently skipped required/repeated changes on protobuf 7.
- `DatabasePool` selected FDB API version 710 while the rest of the package used
  740; FDB only allows one API version per process. The API version is now
  selected in one place and an API version chosen by the application is kept.
- `from fdb_record_layer.expressions import field` (and `concat`, `nest`,
  `record_type`) returned the submodule instead of the helper function.
- The declared `protobuf>=3.20.0` dependency was wrong: the bundled generated code
  needs protobuf 6.33.2 or newer.
- `examples/comprehensive_example.py` crashed in the utilities and schema
  evolution sections.
- README examples used APIs that don't exist. The Quick Start is now taken from
  `examples/quickstart.py`, which CI runs against a real FoundationDB.

### Changed
- Supported Python versions are now 3.11 to 3.15 (3.10 reached end of life).
- Supported FoundationDB versions are 7.4 and 8.0; CI runs integration tests
  against 7.4.10 and 8.0.1. The `foundationdb` Python package must match the
  client library's major.minor version.
- Minimum dependency versions: `foundationdb>=7.4.0`, `protobuf>=6.33.2`,
  `lark>=1.3.1` (sql extra), and current releases of the dev tools.
- Removed the unused `grpc` extra.
- Package ships a `py.typed` marker.
- GitHub Actions updated to the latest major versions; Dependabot updates are grouped.

### Added
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, issue and PR templates.

## [0.1.0b7] - 2025-12-31 (not published to PyPI)

### Added
- Java Record Layer storage and wire format compatibility (`JavaCompatibleStore`).
- Comprehensive e-commerce example and protobuf/FDB configuration docs.

## [0.1.0b4] - 2025-12-27 (not published to PyPI)

### Changed
- Upgraded to FoundationDB 7.4.5 (API version 740).

## [0.1.0b2] - 2025-12-26

### Added
- Integration tests against a real FoundationDB in CI.

## [0.1.0b1] - 2025-12-26

- Initial release.

[Unreleased]: https://github.com/mirkomikulic/fdb-record-layer-python/compare/v0.1.0b8...HEAD
[0.1.0b8]: https://github.com/mirkomikulic/fdb-record-layer-python/compare/v0.1.0-beta.2...v0.1.0b8
[0.1.0b2]: https://github.com/mirkomikulic/fdb-record-layer-python/compare/v0.1.0-beta.1...v0.1.0-beta.2
[0.1.0b1]: https://github.com/mirkomikulic/fdb-record-layer-python/releases/tag/v0.1.0-beta.1
