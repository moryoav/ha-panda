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

See [docs/font-previews.md](../docs/font-previews.md) for a dry-run preview of every font on the 2.13" and 2.66" canvases.

## Fonts

| Family | Files | Hangul | License |
| --- | --- | --- | --- |
| Noto Sans KR | `NotoSansKR-*.ttf` | Yes | SIL OFL 1.1 |
| Gmarket Sans | `GmarketSansTTF*.ttf` | Yes | SIL OFL 1.1 (eBay Korea) |
| CookieRun | `CookieRun*.ttf` | Yes | Devsisters free font, see vendor terms |
| Ownglyph Park DaHyun | `OwnglyphParkDaHyun.ttf` | Yes | VoyagerX free font, see vendor terms |
| Atkinson Hyperlegible | `AtkinsonHyperlegible-Regular.ttf`, `AtkinsonHyperlegible-Bold.ttf` | No | SIL OFL 1.1 |
| B612 | `B612-Regular.ttf`, `B612-Bold.ttf` | No | SIL OFL 1.1 |
| DejaVu Sans | `DejaVuSans.ttf`, `DejaVuSans-Bold.ttf` | No | Bitstream Vera license |
| Liberation Sans | `LiberationSans-Regular.ttf`, `LiberationSans-Bold.ttf` | No | SIL OFL 1.1 |
| Silkscreen | `Silkscreen-Regular.ttf`, `Silkscreen-Bold.ttf` | No | SIL OFL 1.1 |
| Press Start 2P | `PressStart2P-Regular.ttf` | No | SIL OFL 1.1 |
| Tiny5 | `Tiny5-Regular.ttf` | No | SIL OFL 1.1 |
| DotGothic16 | `DotGothic16-Regular.ttf` | No (Japanese) | SIL OFL 1.1 |
| Galmuri | `Galmuri11.ttf`, `Galmuri11-Bold.ttf`, `Galmuri14.ttf` | Yes | SIL OFL 1.1 |
| Terminus TTF | `TerminusTTF.ttf`, `TerminusTTF-Bold.ttf` | No | SIL OFL 1.1 |
| VT323 | `VT323-Regular.ttf` | No | SIL OFL 1.1 |
| Pixelify Sans | `PixelifySans.ttf` | No | SIL OFL 1.1 |
| Jersey 10 | `Jersey10-Regular.ttf` | No | SIL OFL 1.1 |

License texts for the fonts added for small-screen use are in [licenses](licenses/).
