# Changelog

## 0.1.3 - 2026-06-11

- Add ACK-gated PANDA image transfers using chunk progress notifications.
- Wait for the final commit notification before treating a write as complete.
- Retry the whole BLE write at most once on ACK failure or timeout.
- Cap the write attempts option at two attempts.

## 0.1.2 - 2026-06-11

- Add the Packet Notification Capture diagnostic switch.
- Write packet notification traces to `config/panda_esl_traces/`.
- Expose compact trace summary attributes after writes.
