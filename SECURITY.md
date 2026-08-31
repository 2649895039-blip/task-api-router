# Security Policy

## Supported versions

Security fixes are provided for the latest minor release only.

## Reporting a vulnerability

Do not publish vulnerability details involving credentials, arbitrary command
execution, path traversal, or sensitive log disclosure. Use GitHub's private
vulnerability reporting when available; otherwise open a minimal issue asking
the maintainer for a private reporting channel without including exploit details.

Include the affected version, reproduction steps, impact, and a minimal proof of
concept. Do not include real API keys, customer data, or private task content.

## Security boundaries

- API keys should be supplied through environment variables.
- New run logs redact task content unless `--log-content` is explicitly enabled.
- The action guard is defense in depth and does not replace Claude Code permissions,
  operating-system isolation, or provider-side spending limits.
- Model endpoints and proxies are trusted administrator configuration.
