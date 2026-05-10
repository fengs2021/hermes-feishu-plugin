# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.6.x   | :white_check_mark: |
| < 0.6   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly.

**Please do NOT report security vulnerabilities through public GitHub Issues.**

Instead, please use one of the following methods:

### Method 1: GitHub Security Advisories (Preferred)

1. Go to the [Security Advisories](https://github.com/zirflow/hermes-feishu-plugin-1/security/advisories/new) page
2. Click "Report a vulnerability"
3. Fill in the details and submit

This allows us to coordinate disclosure privately before any public announcement.

### Method 2: Email

Send details to: **security@zirflow.com**

Please include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fixes (optional)

### Response Timeline

- **Initial Response**: Within 48 hours
- **Assessment**: Within 7 days
- **Fix Timeline**: Depends on severity, typically 7-30 days
- **Public Disclosure**: After fix is released with credit to reporter

## Security Best Practices (For Users)

When deploying hermes-feishu-plugin-1:

1. **Keep the plugin updated** — Always run the latest stable version
2. **Protect your Gateway** — Ensure your Hermes Gateway is behind appropriate network controls
3. **Limit API Key Exposure** — Never commit API keys to version control
4. **Review Webhook Signatures** — Verify HMAC signatures on incoming webhook requests
5. **Monitor Logs** — Watch for unusual patterns in agent behavior

## Security Updates

Security updates will be announced through:

- GitHub Security Advisories
- Release notes (marked with 🔒 prefix)

Thank you for helping keep hermes-feishu-plugin-1 secure.
