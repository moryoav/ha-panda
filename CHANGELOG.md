# Changelog

## 0.1.13 - 2026-08-02

- Add a font preview gallery for the bundled and optional text fonts.
- Simplify HACS installation instructions now that PANDA ESL is available in the default HACS catalog.

## 0.1.12 - 2026-06-27

- Trim the HACS runtime package by keeping only the default Noto Sans KR fonts and Material Design Icons files inside the integration.
- Move optional decorative font files to `optional_fonts/` so they remain downloadable from GitHub without being installed by HACS.
- Add support for user fonts under `config/panda_esl/fonts/` while keeping `config/www/fonts/` and absolute-path font references working.
- Cache loaded TrueType fonts and compact the Material Design Icons metadata used by icon rendering.
- Configure HACS releases to use the `panda_esl.zip` integration asset and hide the default branch download option.

## 0.1.11 - 2026-06-16

- Disable in-place chunk retries after traces showed duplicate chunk writes can stall transfers and leave labels unable to start the next write.
- Keep the write retry option as retries after the first send, but apply it to full write attempts.

## 0.1.10 - 2026-06-16

- Restore preview and last-updated image entities after Home Assistant restarts.

## 0.1.9 - 2026-06-16

- Add a Bluetooth RSSI diagnostic sensor that reports the latest advertised signal strength in dBm.

## 0.1.8 - 2026-06-16

- Retry timed-out image chunks inside the active BLE write before falling back to a full write retry.
- Change the write retry option so `0` disables retries and higher values count retries after the first send.

## 0.1.7 - 2026-06-12

- Add a write progress sensor that reports BLE image transfer progress from 0 to 100%.
- Update progress after each acknowledged image chunk and mark completion after the final commit notification.

## 0.1.6 - 2026-06-12

- Add GitHub Actions validation workflows for HACS and hassfest.
- Enable HACS README rendering.
- Update write service metadata to use a HACS/hassfest-compatible PANDA ESL device selector.

## 0.1.5 - 2026-06-11

- Add `quality_scale.yaml` tracking for Home Assistant gold quality-scale rules.
- Add config-entry diagnostics, reconfiguration, translated entity/icon/exception metadata, and platform parallel update limits.
- Improve availability logging, stale device removal handling, and guarded diagnostic entity defaults.
- Expand README documentation with supported devices, entities, options, actions, troubleshooting, removal, and use cases.

## 0.1.4 - 2026-06-11

- Move the integration icon into `custom_components/panda_esl/brand/` so Home Assistant can load local custom-integration branding.

## 0.1.3 - 2026-06-11

- Add ACK-gated PANDA image transfers using chunk progress notifications.
- Wait for the final commit notification before treating a write as complete.
- Retry the whole BLE write at most once on ACK failure or timeout.
- Cap the write attempts option at two attempts.

## 0.1.2 - 2026-06-11

- Add the Packet Notification Capture diagnostic switch.
- Write packet notification traces to `config/panda_esl_traces/`.
- Expose compact trace summary attributes after writes.
