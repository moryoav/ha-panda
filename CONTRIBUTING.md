# Contributing to PANDA ESL for Home Assistant

Thanks for your interest in improving PANDA ESL for Home Assistant.

This project is a Home Assistant custom integration for PANDA / ETAG BLE electronic shelf labels. It provides Bluetooth config flow support, PANDA image writes, diagnostics, image entities, guarded write behavior, and a Gicisky-compatible service payload renderer.

Contributions are welcome, including bug reports, documentation improvements, compatibility fixes, renderer improvements, security hardening, and feature ideas.

## Before You Start

Please open an issue before starting large or risky changes. This helps avoid duplicated work and gives maintainers a chance to discuss the approach first.

Small fixes, documentation updates, and clearly scoped bug fixes can usually go straight to a pull request.

## Reporting Bugs

When reporting a bug, please include:

- The PANDA ESL version you are using.
- Your Home Assistant version.
- Whether you installed through HACS, manually, or from the development branch.
- Your Home Assistant host type and Bluetooth adapter setup.
- The PANDA / ETAG label model or advertised name, if known.
- Clear steps to reproduce the issue.
- Relevant Home Assistant logs and PANDA ESL diagnostics with sensitive information removed.
- What you expected to happen.
- What actually happened.

Please remove secrets, tokens, private URLs, Bluetooth MAC addresses when not needed, personal paths, and private Home Assistant configuration before sharing logs or screenshots.

## Suggesting Features

Feature requests are welcome. Please describe:

- The problem you want to solve.
- The Home Assistant workflow or automation you expect to use.
- The label hardware and display size you want to support.
- Whether the change affects Bluetooth writes, rendering, entities, diagnostics, options, or documentation.
- Any reliability, battery, privacy, or safety concerns the feature may introduce.

Because this project writes to physical display hardware over Bluetooth, features that change transfer timing, retry behavior, duplicate prevention, write locking, or packet capture should include a clear rationale and a test plan.

## Development Setup

Clone the repository:

```bash
git clone https://github.com/moryoav/ha-panda.git
cd ha-panda
```

The repository layout is:

```text
custom_components/panda_esl/   Home Assistant custom integration
examples/                      Example Home Assistant scripts and service payloads
tests/                         Pytest coverage for repository metadata and quality rules
hacs.json                      HACS repository metadata
```

For local Home Assistant testing, install or copy the integration into:

```text
/config/custom_components/panda_esl
```

Then restart Home Assistant and add **PANDA ESL** from **Settings** -> **Devices & services**.

## Pull Request Guidelines

Please keep pull requests focused. A good pull request should:

- Explain what changed and why.
- Mention any related issue.
- Keep unrelated formatting or refactoring out of the change.
- Update documentation when behavior, installation, options, actions, entities, diagnostics, or supported devices change.
- Include screenshots or rendered image examples when changing output rendering.
- Include Bluetooth trace or diagnostic notes when changing write behavior, if practical.
- Avoid committing secrets, credentials, private logs, Bluetooth addresses, or private Home Assistant configuration.

If you change integration behavior, update `README.md`, `CHANGELOG.md`, and translations where appropriate.

## Testing

Before opening a pull request, test the parts you changed as much as practical.

Run the local pytest stack with the Windows shim used by this repository:

```powershell
C:\Users\Yoav\bin\pytest.cmd
```

Useful targeted runs:

```powershell
C:\Users\Yoav\bin\pytest.cmd tests
C:\Users\Yoav\bin\pytest.cmd tests -q
```

For integration changes, verify that Home Assistant can:

- Load the `panda_esl` integration.
- Complete the config flow for a discovered or manually selected label.
- Create the expected entities.
- Call `panda_esl.write` and `panda_esl.write_guarded`.
- Reload or restart without errors.

For Bluetooth write changes, verify as much as possible that:

- A supported label is visible to Home Assistant Bluetooth.
- Diagnostic fill buttons still write known-good images.
- ACK-gated image chunks complete without timeout.
- Retry and failure paths report useful translated errors.
- Packet notification capture does not expose unnecessary private data.

For renderer changes, include examples that cover the changed payload element, color behavior, rotation, and dry-run preview output.

For documentation-only changes, please check that links, paths, examples, and Home Assistant UI names are accurate.

## Security Notes

This project can interact with nearby BLE shelf labels and can write rendered content to physical display hardware. Please be especially careful with changes involving:

- Bluetooth discovery, connection selection, and advertised metadata.
- BLE packet framing, chunk timing, retries, ACK handling, and trace capture.
- Home Assistant service calls and target device resolution.
- Diagnostics and log output.
- File writes under the Home Assistant config directory.
- Rendering remote images or user-provided payload data.

Do not include real credentials, API tokens, private URLs, private logs, Bluetooth addresses, or personal Home Assistant configuration in issues or pull requests.

If you believe you found a security vulnerability, please do not open a public issue with exploit details. Use the project's security reporting process if available, or contact the maintainer privately.

## Documentation

Please update documentation when changing user-facing behavior. Depending on the change, this may include:

- `README.md`
- `CHANGELOG.md`
- `custom_components/panda_esl/services.yaml`
- `custom_components/panda_esl/strings.json`
- `custom_components/panda_esl/translations/en.json`
- `examples/`

Use plain, direct language and include Home Assistant examples where they make the workflow easier to understand.

## Releases

Stable users should use the default repository URL:

```text
https://github.com/moryoav/ha-panda
```

Development testing may happen from branches or unreleased commits. If you test development builds through HACS, make sure you know which branch or commit you installed.

## Code of Conduct

Please be respectful, constructive, and patient. This project is intended to help Home Assistant users work more effectively with their own PANDA / ETAG labels, and contributions should support that goal.
