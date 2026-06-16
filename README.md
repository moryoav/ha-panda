# PANDA ESL for Home Assistant
[![HACS][hacs-badge]][hacs-url] [![release][release-badge]][release-url] ![downloads][downloads-badge] [![license](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)

Home Assistant custom integration for PANDA / ETAG BLE electronic shelf labels.

This integration was built from the reverse-engineered PANDA write protocol in this repository. It keeps the working PANDA pixel transfer path and adds a Gicisky-compatible service API for rendering text, shapes, images, icons, QR codes, barcodes, tables, plots, gauges, and progress bars.

## Features

- Bluetooth config flow for supported PANDA / ETAG labels
- Diagnostic buttons for known-good fill and framed-image writes
- `panda_esl.write` service compatible with the `gicisky.write` payload syntax
- `panda_esl.write_guarded` service with duplicate, write-lock, and debounce guards
- Preview and last-updated image entities
- Write progress percentage sensor updated after each acknowledged image chunk
- Bluetooth RSSI diagnostic sensor from the latest Home Assistant Bluetooth advertisement
- Write-lock switch
- Packet notification capture switch for BLE transfer diagnostics
- Bundled fonts and Material Design Icons support

The PANDA display supports white, black, and red output. The service syntax accepts `yellow` for compatibility with Gicisky payloads, but yellow is mapped to red when writing to PANDA hardware.

## Supported Devices

Known supported devices:

- PANDA / ETAG 2.13 inch BLE electronic shelf labels that advertise as `ETAG-*`
- Confirmed working product: [PANDA / ETAG BLE electronic shelf label](https://s.click.aliexpress.com/e/_c4Kgtn93)

![PANDA / ETAG BLE electronic shelf label](https://raw.githubusercontent.com/moryoav/ha-panda/main/images/device.jpg)

- Labels advertising PANDA service UUID `18424398-7cbc-11e9-8f9e-2a86e4005a59`
- ETAG 525-style labels advertising service UUID `33323032-4c53-4545-4c42-4b4e494c4f57`

Unsupported or unverified devices:

- Wi-Fi or cloud-managed ESL labels
- BLE labels that do not use the PANDA `AC ... CA` image packet protocol
- Displays with a resolution other than 256x128

## Installation

### HACS

[![Open the PANDA ESL HACS repository](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=moryoav&repository=ha-panda&category=integration)

1. Open HACS in Home Assistant.
2. Add `https://github.com/moryoav/ha-panda` as an integration custom repository.
3. Search for **PANDA ESL** and install it.
4. Restart Home Assistant.
5. Add the integration from **Settings** -> **Devices & services** -> **Add integration** -> **PANDA ESL**.

### Manual

1. Copy `custom_components/panda_esl` to `config/custom_components/panda_esl`.
2. Restart Home Assistant.
3. Add the integration from **Settings** -> **Devices & services** -> **Add integration** -> **PANDA ESL**.

## Configuration

[![Add the PANDA ESL integration](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=panda_esl)

The integration is configured through the Home Assistant UI. If Home Assistant discovers a supported PANDA / ETAG label over Bluetooth, select it from the discovered devices list. You can also start the config flow manually from **Settings** -> **Devices & services** -> **Add integration** -> **PANDA ESL**.

### Options

Open **Settings** -> **Devices & services** -> **PANDA ESL** -> **Configure** to adjust write behavior:

| Option | Default | Description |
| --- | ---: | --- |
| Write retries | `1` | Retries after the first send. `0` disables retries; higher values retry failed chunks or whole writes when needed. |
| Write delay | `150 ms` | Delay between PANDA preamble packets. Image chunks advance on device progress notifications. |
| Prevent duplicate send | `false` | Skip guarded writes when the rendered image matches the last rendered image. |
| Debounce delay | `0 ms` | Delay guarded writes so newer writes can replace pending writes. `0` disables debounce. |

Use **Reconfigure** from the integration entry menu to update the display name stored by the integration and refresh Bluetooth advertisement metadata when the label is currently visible.

## Entities

Each configured label creates one Home Assistant device.

| Entity | Category | Enabled by default | Description |
| --- | --- | --- | --- |
| Last updated content | None | Yes | PNG image of the last payload successfully written to the label. |
| Preview content | Diagnostic | Yes | PNG preview of the last rendered payload, including dry runs. |
| Write progress | None | Yes | Percentage progress for the active or most recent BLE image write, with chunk counts as attributes. |
| Bluetooth RSSI | Diagnostic | Yes | Latest advertised Bluetooth signal strength in dBm. |
| Write lock | Configuration | Yes | Prevents `panda_esl.write_guarded` from physically writing to the label. |
| Packet notification capture | Diagnostic | No | Writes detailed BLE packet and notification traces to `config/panda_esl_traces/`. |
| Send white fill | Diagnostic | No | Sends a known-good full white diagnostic image. |
| Send black fill | Diagnostic | No | Sends a known-good full black diagnostic image. |
| Send red fill | Diagnostic | No | Sends a known-good full red diagnostic image. |
| Send framed image | Diagnostic | No | Sends a framed diagnostic image for orientation and border checks. |

## Actions

The actions intentionally mirror the Gicisky payload syntax, but use PANDA's BLE packet format when writing the rendered pixels.

```yaml
action: panda_esl.write
target:
  device_id: YOUR_DEVICE_ID
data:
  background: white
  payload:
    - type: text
      value: Hello PANDA
      x: 10
      y: 10
      size: 32
      color: black
    - type: rectangle
      x_start: 8
      y_start: 52
      x_end: 120
      y_end: 110
      outline: black
      fill: red
      width: 2
```

Use `dry_run: true` to update the preview image entity without writing to the physical label.

```yaml
action: panda_esl.write_guarded
target:
  device_id: YOUR_DEVICE_ID
data:
  debounce_override_ms: 0
  payload:
    - type: text
      value: Immediate guarded write
      x: 10
      y: 10
      size: 24
```

### Action Parameters

| Parameter | Required | Description |
| --- | --- | --- |
| `payload` | Yes | List of drawing elements. See Supported Payload Elements below. |
| `rotate` | No | Rotation in degrees: `0`, `90`, `180`, or `270`. |
| `background` | No | `white`, `black`, `red`, or `yellow`. Yellow maps to red on PANDA hardware. |
| `threshold` | No | Black threshold from `0` to `255`. Default is `128`. |
| `red_threshold` | No | Red/yellow threshold from `0` to `255`. Default is `128`. |
| `dry_run` | No | Render and update the preview without sending BLE packets. |
| `debounce_override_ms` | No | `write_guarded` only. Overrides the configured debounce delay for this call. |

`panda_esl.write` sends immediately. `panda_esl.write_guarded` applies duplicate prevention, write lock, and debounce settings before sending.

## Supported Payload Elements

The renderer supports the same element names and field names used by `hass-gicisky`:

`text`, `multiline`, `line`, `rectangle`, `rectangle_pattern`, `circle`, `ellipse`, `icon`, `dlimg`, `qrcode`, `barcode`, `datamatrix`, `diagram`, `plot`, `progress_bar`, `arc`, `gauge`, `polygon`, `table`, and `text_box`.

## Data Updates

PANDA ESL is a local push Bluetooth integration. Home Assistant updates runtime state when Bluetooth advertisements are received and marks write buttons unavailable when the label leaves the Bluetooth cache. Image entities update only after a render or successful write. The integration does not poll a cloud service.

The Bluetooth RSSI sensor updates from the latest advertisement Home Assistant receives for the label. It is a last-advertised signal value in dBm, not a continuously measured connection-quality percentage.

Writes use a connectable BLE handle at action time. If no connectable handle is available, Home Assistant raises a translated action error and records the failure in the diagnostic attributes.

The Write progress sensor resets to 0% when a physical write attempt starts, advances after each acknowledged image chunk, and reaches 100% only after the final commit notification is received.

## Examples

Example scripts for the 256x128 PANDA display live in [examples](examples/).

| Size | Example | Preview | YAML |
| --- | --- | --- | --- |
| 2.13" (256x128) | Calendar | ![Calendar example](https://raw.githubusercontent.com/moryoav/ha-panda/main/images/calendar.png) | [2.13" Calendar](https://github.com/moryoav/ha-panda/blob/main/examples/2.13-calendar.yaml) |
| 2.13" (256x128) | Wi-Fi QR | ![Wi-Fi QR example](https://raw.githubusercontent.com/moryoav/ha-panda/main/images/wifi.png) | [2.13" Wi-Fi QR](https://github.com/moryoav/ha-panda/blob/main/examples/2.13-wifi.yaml) |
| 2.13" (256x128) | Vacation countdown | ![Vacation countdown example](https://raw.githubusercontent.com/moryoav/ha-panda/main/images/dayleft.png) | [2.13" Vacation countdown](https://github.com/moryoav/ha-panda/blob/main/examples/2.13-vacation-countdown.yaml) |
| 2.13" (256x128) | Weather today | ![Weather today example](https://raw.githubusercontent.com/moryoav/ha-panda/main/images/weather-today.png) | [2.13" Weather today](https://github.com/moryoav/ha-panda/blob/main/examples/2.13-weather-today.yaml) |
| 2.13" (256x128) | Weather forecast | ![Weather forecast example](https://raw.githubusercontent.com/moryoav/ha-panda/main/images/weather.png) | [2.13" Weather forecast](https://github.com/moryoav/ha-panda/blob/main/examples/2.13-weather-forecast.yaml) |

## Use Cases

- Show a small daily calendar, weather forecast, or reminder on a shelf label.
- Render QR codes, barcodes, and short status messages from Home Assistant automations.
- Use `write_guarded` with debounce to prevent rapid repeated writes when multiple entities change together.
- Use `dry_run` to preview a rendered payload before writing it to a physical label.

## Known Limitations

- The known-good PANDA write path sends two image planes through the `0000ffe1-0000-1000-8000-00805f9b34fb` characteristic using the reverse-engineered `AC ... CA` packet framing.
- PANDA image chunks are ACK-gated using device progress notifications. Timed-out chunks are retried in-place before falling back to a full write retry.
- The default write delay is 150 ms for preamble packets; image chunks advance after ACK progress.
- The supported canvas size is 256x128 pixels.
- Yellow payload colors are rendered as red on PANDA hardware.
- A label must be visible to Home Assistant Bluetooth before a physical write can start.
- `plot` elements require Home Assistant Recorder history for the referenced entities.

## Diagnostics and Troubleshooting

Use **Download diagnostics** from the PANDA ESL device entry to collect redacted config, runtime state, and write summaries. Turn on the **Packet notification capture** diagnostic switch to write JSONL transfer traces under `config/panda_esl_traces/`. Entity attributes keep only the summary and latest trace file path.

Common issues:

| Symptom | What to check |
| --- | --- |
| No labels are discovered | Confirm a Bluetooth adapter is enabled, move the label closer, and wait for the label to advertise as `ETAG-*`. |
| Write action fails with no connectable Bluetooth handle | Wait for a fresh advertisement, move closer to the adapter, or restart the label if possible. |
| Rendered image is visible in Preview but not on the label | Disable Write lock, check that Packet notification capture does not show ACK timeouts, and try a diagnostic fill button. |
| Plot element fails | Confirm Recorder is enabled and the referenced entity has numeric history in the requested time range. |

## Removal

1. Remove the PANDA ESL integration entry from **Settings** -> **Devices & services**.
2. Restart Home Assistant if you plan to delete the custom component files.
3. Remove `custom_components/panda_esl` from your Home Assistant config directory, or uninstall the integration from HACS.
4. Optional: delete old packet trace files from `config/panda_esl_traces/`.

## Development

The HACS repository layout is:

```text
custom_components/panda_esl/
  brand/icon.png
hacs.json
README.md
```

All files needed at runtime live under `custom_components/panda_esl/`, as required by HACS integration repositories.

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=flat-square
[hacs-url]: https://github.com/hacs/integration
[release-badge]: https://img.shields.io/github/v/release/moryoav/ha-panda?style=flat-square
[release-url]: https://github.com/moryoav/ha-panda/releases
[downloads-badge]: https://img.shields.io/github/downloads/moryoav/ha-panda/total?style=flat-square

## Disclaimer

I am not affiliated with PANDA, ETAG, AliExpress, or any seller or manufacturer of the referenced devices. Use this custom component at your own risk. I am not responsible for any damage to your device, data loss, hardware malfunction, or other issues caused by using this component.
