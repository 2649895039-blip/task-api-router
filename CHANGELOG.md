# Changelog

## 0.3.0 - 2026-08-31

- Use native Claude Code `allow` / `ask` / `deny` hook decisions.
- Skip DAG tasks whose upstream dependencies failed.
- Retry transient provider failures with exponential backoff.
- Bound concurrent model calls and add per-run soft cost/token limits.
- Redact task content from new logs by default and create private log files.
- Validate model URLs, timeouts, token limits, costs, and environment variable names.
- Declare compatibility with OpenAI Python SDK 1.x and 2.x.
- Test Python 3.10-3.12 on both Ubuntu and Windows.

## 0.2.1 - 2026-08-22

- Align CLI and plugin version metadata.
- Publish Claude Code and OpenClaw integration structure.
