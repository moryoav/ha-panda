# Support

Thanks for using PANDA ESL for Home Assistant.

## Getting Help

Start with the project documentation:

- `README.md` for installation, setup, supported devices, entities, actions, examples, troubleshooting, and removal.
- `examples/` for ready-to-adapt Home Assistant service payloads.
- `CHANGELOG.md` for release notes and behavior changes.

## Share Your Project

Made something with PANDA ESL? Post a photo in the [Home Assistant Community thread](https://community.home-assistant.io/t/panda-e-ink-ble-electronic-shelf-label-esl/1013663). Feel free to share the YAML too.

## Reporting Bugs

Use the bug report issue template when something is not working as expected.

Please include:

- Your PANDA ESL version.
- Your Home Assistant version.
- Your installation method.
- Your Home Assistant host type and Bluetooth adapter setup.
- The PANDA / ETAG label model, display size, or advertised name, if known.
- Clear reproduction steps.
- Relevant Home Assistant logs and diagnostics with sensitive information removed.

Do not include secrets, tokens, private URLs, Bluetooth MAC addresses when not needed, personal paths, or private Home Assistant configuration.

## Feature Requests

Use the feature request issue template for new ideas or improvements.

Please explain the Home Assistant workflow you want to improve, the label hardware involved, and whether you think the change belongs in Bluetooth writes, rendering, entities, diagnostics, options, examples, or documentation.

## Security Issues

If you believe you found a security vulnerability, do not open a public issue with exploit details. Follow `SECURITY.md`.

## Scope of Support

This project is provided by the community and may not have immediate support. Keep backups of your Home Assistant configuration, test new service payloads with `dry_run: true` when possible, and use the write lock option when you want to prevent physical label updates.
