# Security Policy

PANDA ESL for Home Assistant can discover nearby BLE shelf labels and write rendered content to physical display hardware. Please treat security, privacy, and diagnostics issues with care.

## Supported Versions

Security fixes are intended for the latest published release and the current `main` branch.

Older releases are not actively supported unless a maintainer says otherwise in a specific issue or release note.

## Reporting a Vulnerability

Please do not open a public issue with exploit details, working proof-of-concept code, private logs, tokens, private URLs, Bluetooth addresses, or personal Home Assistant configuration.

If GitHub private vulnerability reporting is available for this repository, use the **Report a vulnerability** button on the Security tab.

If private vulnerability reporting is not available, open a minimal public issue that says you have a security concern and asks the maintainer to arrange private disclosure. Do not include sensitive details in that issue.

## What to Include

When reporting a vulnerability privately, include as much of the following as you can safely share:

- A clear description of the issue.
- The affected version or commit.
- Whether the issue affects Bluetooth discovery, write services, rendering, diagnostics, examples, or documentation.
- Steps to reproduce in a safe test environment.
- The expected impact.
- Any relevant logs with secrets and private configuration removed.
- Suggested mitigations, if you know them.

## Security-Sensitive Areas

Please use extra care when changing or reviewing:

- Bluetooth discovery, device matching, and connectable handle selection.
- BLE packet framing, chunk timing, ACK handling, retries, and timeouts.
- Packet notification capture and diagnostics.
- Home Assistant service target resolution.
- Rendering of user-provided payloads, remote images, QR codes, barcodes, and icons.
- File writes under the Home Assistant config directory.
- Logs, translated errors, entity attributes, and downloaded diagnostics.

## Responsible Testing

Test security reports and fixes only in an environment you own or have permission to use. Do not attempt to access, modify, disrupt, or disclose another person's Home Assistant instance, configuration, credentials, logs, Bluetooth devices, or labels.

## Public Disclosure

Please give the maintainer reasonable time to investigate and fix confirmed vulnerabilities before publishing details publicly. Coordinated disclosure helps protect users while a fix is prepared.
