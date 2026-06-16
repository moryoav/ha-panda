# Changelog

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
