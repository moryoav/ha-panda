# PANDA ESL for Home Assistant

Home Assistant custom integration for PANDA / ETAG BLE electronic shelf labels.

This integration was built from the reverse-engineered PANDA write protocol in this repository. It keeps the working PANDA pixel transfer path and adds a Gicisky-compatible service API for rendering text, shapes, images, icons, QR codes, barcodes, tables, plots, gauges, and progress bars.

## Features

- Bluetooth config flow for supported PANDA / ETAG labels
- Diagnostic buttons for known-good fill and framed-image writes
- `panda_esl.write` service compatible with the `gicisky.write` payload syntax
- `panda_esl.write_guarded` service with duplicate, write-lock, and debounce guards
- Preview and last-updated image entities
- Write-lock switch
- Bundled fonts and Material Design Icons support

The PANDA display supports white, black, and red output. The service syntax accepts `yellow` for compatibility with Gicisky payloads, but yellow is mapped to red when writing to PANDA hardware.

## HACS Installation

1. In HACS, open the three-dot menu and choose **Custom repositories**.
2. Add this repository URL:

   `https://github.com/moryoav/ha-panda`

3. Select **Integration** as the category.
4. Install **PANDA ESL**.
5. Restart Home Assistant.
6. Add the integration from **Settings > Devices & services**.

## Services

The services intentionally mirror the Gicisky payload syntax, but use PANDA's BLE packet format when writing the rendered pixels.

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

## Supported Payload Elements

The renderer supports the same element names and field names used by `hass-gicisky`:

`text`, `multiline`, `line`, `rectangle`, `rectangle_pattern`, `circle`, `ellipse`, `icon`, `dlimg`, `qrcode`, `barcode`, `datamatrix`, `diagram`, `plot`, `progress_bar`, `arc`, `gauge`, `polygon`, `table`, and `text_box`.

## Notes

- The known-good PANDA write path sends two image planes through the `0000ffe1-0000-1000-8000-00805f9b34fb` characteristic using the reverse-engineered `AC ... CA` packet framing.
- The default write delay is 150 ms to preserve the reliable timing used by the diagnostic framed-image button.
- `plot` elements require Home Assistant Recorder history for the referenced entities.

## Development

The HACS repository layout is:

```text
custom_components/panda_esl/
brand/icon.png
hacs.json
README.md
```

All files needed at runtime live under `custom_components/panda_esl/`, as required by HACS integration repositories.
