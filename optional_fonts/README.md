# Optional Fonts

These fonts are not installed by HACS. They are kept in the repository so users can download only the fonts they need.

To use one of these fonts, copy it into your Home Assistant config directory:

```text
config/panda_esl/fonts/
```

Then reference the file name in a PANDA ESL payload:

```yaml
font: GmarketSansTTFBold.ttf
```

Existing payloads that use the old bundled path, such as `fonts/GmarketSansTTFBold.ttf`, also work after the font has been copied into `config/panda_esl/fonts/`.
