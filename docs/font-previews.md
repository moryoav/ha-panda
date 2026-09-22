# Font Previews

These previews were generated with the same renderer that `panda_esl.write` uses for `dry_run: true`, so they show exactly the pixels that reach the label. Two canvases are shown for every font:

| Column | Label | Canvas | `PANDA` size | `ABC 123` size |
| --- | --- | --- | --- | --- |
| 2.13" | ETAG-525 | 256x128 | 48 | 32 |
| 2.66" | ETAG-526 | 296x152 | 56 | 40 |

Pixel fonts are rendered at the nearest whole multiple of their native grid instead of the sizes above (see [Pixel fonts](#pixel-fonts)). The exact size used for each image is listed in [sizes.json](../images/font-previews/sizes.json).

Text on PANDA labels is drawn in 1-bit mode: every pixel is either black or white, there is no anti-aliasing. That is why diagonal and curved strokes show stair-steps. The only ways to reduce the effect are to use a font with good hinting for monochrome rendering, or to use a font that was drawn on a pixel grid and render it at a multiple of that grid.

Optional fonts are available in [optional_fonts](../optional_fonts/). Copy any optional `.ttf` file you want to use into `config/panda_esl/fonts/`, then reference the file name in a payload. To regenerate this gallery run `python tools/generate_font_previews.py` from the repository root.

## Bundled and Korean fonts

Noto Sans KR Regular and Bold ship with the integration. The rest are optional downloads. All of these fonts cover Hangul.

| Font | File | 2.13" (256x128) | 2.66" (296x152) |
| --- | --- | --- | --- |
| Noto Sans KR Thin | `NotoSansKR-Thin.ttf` | ![Noto Sans KR Thin](../images/font-previews/noto-sans-kr-thin.png) | ![Noto Sans KR Thin 2.66](../images/font-previews/noto-sans-kr-thin-266.png) |
| Noto Sans KR ExtraLight | `NotoSansKR-ExtraLight.ttf` | ![Noto Sans KR ExtraLight](../images/font-previews/noto-sans-kr-extralight.png) | ![Noto Sans KR ExtraLight 2.66](../images/font-previews/noto-sans-kr-extralight-266.png) |
| Noto Sans KR Light | `NotoSansKR-Light.ttf` | ![Noto Sans KR Light](../images/font-previews/noto-sans-kr-light.png) | ![Noto Sans KR Light 2.66](../images/font-previews/noto-sans-kr-light-266.png) |
| Noto Sans KR Regular | `fonts/NotoSansKR-Regular.ttf` | ![Noto Sans KR Regular](../images/font-previews/noto-sans-kr-regular.png) | ![Noto Sans KR Regular 2.66](../images/font-previews/noto-sans-kr-regular-266.png) |
| Noto Sans KR Medium | `NotoSansKR-Medium.ttf` | ![Noto Sans KR Medium](../images/font-previews/noto-sans-kr-medium.png) | ![Noto Sans KR Medium 2.66](../images/font-previews/noto-sans-kr-medium-266.png) |
| Noto Sans KR SemiBold | `NotoSansKR-SemiBold.ttf` | ![Noto Sans KR SemiBold](../images/font-previews/noto-sans-kr-semibold.png) | ![Noto Sans KR SemiBold 2.66](../images/font-previews/noto-sans-kr-semibold-266.png) |
| Noto Sans KR Bold | `fonts/NotoSansKR-Bold.ttf` | ![Noto Sans KR Bold](../images/font-previews/noto-sans-kr-bold.png) | ![Noto Sans KR Bold 2.66](../images/font-previews/noto-sans-kr-bold-266.png) |
| Noto Sans KR ExtraBold | `NotoSansKR-ExtraBold.ttf` | ![Noto Sans KR ExtraBold](../images/font-previews/noto-sans-kr-extrabold.png) | ![Noto Sans KR ExtraBold 2.66](../images/font-previews/noto-sans-kr-extrabold-266.png) |
| Noto Sans KR Black | `NotoSansKR-Black.ttf` | ![Noto Sans KR Black](../images/font-previews/noto-sans-kr-black.png) | ![Noto Sans KR Black 2.66](../images/font-previews/noto-sans-kr-black-266.png) |
| Gmarket Sans Light | `GmarketSansTTFLight.ttf` | ![Gmarket Sans Light](../images/font-previews/gmarket-sans-light.png) | ![Gmarket Sans Light 2.66](../images/font-previews/gmarket-sans-light-266.png) |
| Gmarket Sans Medium | `GmarketSansTTFMedium.ttf` | ![Gmarket Sans Medium](../images/font-previews/gmarket-sans-medium.png) | ![Gmarket Sans Medium 2.66](../images/font-previews/gmarket-sans-medium-266.png) |
| Gmarket Sans Bold | `GmarketSansTTFBold.ttf` | ![Gmarket Sans Bold](../images/font-previews/gmarket-sans-bold.png) | ![Gmarket Sans Bold 2.66](../images/font-previews/gmarket-sans-bold-266.png) |
| CookieRun Regular | `CookieRunRegular.ttf` | ![CookieRun Regular](../images/font-previews/cookierun-regular.png) | ![CookieRun Regular 2.66](../images/font-previews/cookierun-regular-266.png) |
| CookieRun Bold | `CookieRunBold.ttf` | ![CookieRun Bold](../images/font-previews/cookierun-bold.png) | ![CookieRun Bold 2.66](../images/font-previews/cookierun-bold-266.png) |
| CookieRun Black | `CookieRunBlack.ttf` | ![CookieRun Black](../images/font-previews/cookierun-black.png) | ![CookieRun Black 2.66](../images/font-previews/cookierun-black-266.png) |
| Ownglyph Park DaHyun | `OwnglyphParkDaHyun.ttf` | ![Ownglyph Park DaHyun](../images/font-previews/ownglyph-park-dahyun.png) | ![Ownglyph Park DaHyun 2.66](../images/font-previews/ownglyph-park-dahyun-266.png) |

## Fonts for small monochrome screens

The fonts below were picked because they are known to hold up on low-resolution, black-and-white displays. They fall into two groups:

- **Screen-hinted outline fonts.** Regular vector fonts that were designed for screens and carry TrueType hinting instructions. In 1-bit mode FreeType runs those instructions, which snap stems to whole pixels and keep stroke widths even. They are the safest choice for general text and they cover a wide range of characters.
- **Pixel fonts.** Fonts that were drawn pixel by pixel on a fixed grid and later converted to outlines. Rendered at a whole multiple of that grid they produce no aliasing at all, because every outline edge lands on a pixel boundary. Rendered at any other size they look worse than an ordinary font.

None of these fonts cover Hangul except Galmuri, which is a Korean pixel font. If you need Korean text with a clean pixel look, use Galmuri; otherwise keep using Noto Sans KR.

### Screen-hinted outline fonts

| Font | File | Why it is here | 2.13" (256x128) | 2.66" (296x152) |
| --- | --- | --- | --- | --- |
| Atkinson Hyperlegible Regular | `AtkinsonHyperlegible-Regular.ttf` | Designed by the Braille Institute for low-vision readers. Unambiguous letterforms (`I`/`l`/`1`, `0`/`O`) and open shapes that survive coarse pixels. | ![Atkinson Hyperlegible Regular](../images/font-previews/atkinson-hyperlegible-regular.png) | ![Atkinson Hyperlegible Regular 2.66](../images/font-previews/atkinson-hyperlegible-regular-266.png) |
| Atkinson Hyperlegible Bold | `AtkinsonHyperlegible-Bold.ttf` | Bold weight of the above. | ![Atkinson Hyperlegible Bold](../images/font-previews/atkinson-hyperlegible-bold.png) | ![Atkinson Hyperlegible Bold 2.66](../images/font-previews/atkinson-hyperlegible-bold-266.png) |
| B612 Regular | `B612-Regular.ttf` | Commissioned by Airbus for cockpit screens. Optimised for legibility on low-resolution displays at a distance. | ![B612 Regular](../images/font-previews/b612-regular.png) | ![B612 Regular 2.66](../images/font-previews/b612-regular-266.png) |
| B612 Bold | `B612-Bold.ttf` | Bold weight of the above. | ![B612 Bold](../images/font-previews/b612-bold.png) | ![B612 Bold 2.66](../images/font-previews/b612-bold-266.png) |
| DejaVu Sans | `DejaVuSans.ttf` | Derived from Bitstream Vera, which was hand-hinted for screen rendering. The default sans on most Linux desktops. | ![DejaVu Sans](../images/font-previews/dejavu-sans.png) | ![DejaVu Sans 2.66](../images/font-previews/dejavu-sans-266.png) |
| DejaVu Sans Bold | `DejaVuSans-Bold.ttf` | Bold weight of the above. | ![DejaVu Sans Bold](../images/font-previews/dejavu-sans-bold.png) | ![DejaVu Sans Bold 2.66](../images/font-previews/dejavu-sans-bold-266.png) |
| Liberation Sans Regular | `LiberationSans-Regular.ttf` | Metric-compatible Arial replacement with full TrueType hinting. Narrower than DejaVu, so more text fits per line. | ![Liberation Sans Regular](../images/font-previews/liberation-sans-regular.png) | ![Liberation Sans Regular 2.66](../images/font-previews/liberation-sans-regular-266.png) |
| Liberation Sans Bold | `LiberationSans-Bold.ttf` | Bold weight of the above. | ![Liberation Sans Bold](../images/font-previews/liberation-sans-bold.png) | ![Liberation Sans Bold 2.66](../images/font-previews/liberation-sans-bold-266.png) |

### Pixel fonts

The **Grid** column is the pixel size the font was drawn on. Use `size` values that are whole multiples of it (for example 16, 24, 32, 40, 48 for an 8 px grid). Fonts marked with a dash have no exact grid and can be used at any size; they still keep a pixel look but their edges are not perfectly aligned.

| Font | File | Grid | Sizes used (2.13" / 2.66") | Notes | 2.13" (256x128) | 2.66" (296x152) |
| --- | --- | --- | --- | --- | --- | --- |
| Silkscreen Regular | `Silkscreen-Regular.ttf` | 8 | 48+32 / 56+40 | Classic web pixel font; wide letter spacing. | ![Silkscreen Regular](../images/font-previews/silkscreen-regular.png) | ![Silkscreen Regular 2.66](../images/font-previews/silkscreen-regular-266.png) |
| Silkscreen Bold | `Silkscreen-Bold.ttf` | 8 | 48+32 / 56+40 | Bold weight of the above. | ![Silkscreen Bold](../images/font-previews/silkscreen-bold.png) | ![Silkscreen Bold 2.66](../images/font-previews/silkscreen-bold-266.png) |
| Press Start 2P | `PressStart2P-Regular.ttf` | 8 | 48+32 / 56+40 | Arcade-style, very heavy; the most legible pixel font at a distance but needs a lot of width. | ![Press Start 2P](../images/font-previews/press-start-2p.png) | ![Press Start 2P 2.66](../images/font-previews/press-start-2p-266.png) |
| Tiny5 | `Tiny5-Regular.ttf` | 8 | 48+32 / 56+40 | 5 px cap height on an 8 px em; compact, crisp digits. | ![Tiny5](../images/font-previews/tiny5.png) | ![Tiny5 2.66](../images/font-previews/tiny5-266.png) |
| DotGothic16 | `DotGothic16-Regular.ttf` | 16 | 48+32 / 48+32 | Fontworks 16-dot Japanese font; also covers kana and kanji. Light stroke, tall line height. | ![DotGothic16](../images/font-previews/dotgothic16.png) | ![DotGothic16 2.66](../images/font-previews/dotgothic16-266.png) |
| Galmuri11 | `Galmuri11.ttf` | 12 | 48+36 / 48+36 | Korean pixel font, 11 px glyphs on a 12 px line. Full Hangul coverage. | ![Galmuri11](../images/font-previews/galmuri11.png) | ![Galmuri11 2.66](../images/font-previews/galmuri11-266.png) |
| Galmuri11 Bold | `Galmuri11-Bold.ttf` | 12 | 48+36 / 48+36 | Bold weight of the above. | ![Galmuri11 Bold](../images/font-previews/galmuri11-bold.png) | ![Galmuri11 Bold 2.66](../images/font-previews/galmuri11-bold-266.png) |
| Galmuri14 | `Galmuri14.ttf` | 15 | 45+30 / 45+30 | Larger 14 px Galmuri master on a 15 px line. | ![Galmuri14](../images/font-previews/galmuri14.png) | ![Galmuri14 2.66](../images/font-previews/galmuri14-266.png) |
| Terminus TTF | `TerminusTTF.ttf` | - | 48+32 / 56+40 | Terminal font with embedded bitmaps at 12, 14, 16, 18, 20, 22, 24, 28 and 32 px. At those sizes the bitmap is used directly; larger sizes use the scaled outline. | ![Terminus TTF](../images/font-previews/terminus.png) | ![Terminus TTF 2.66](../images/font-previews/terminus-266.png) |
| Terminus TTF Bold | `TerminusTTF-Bold.ttf` | - | 48+32 / 56+40 | Bold weight of the above. | ![Terminus TTF Bold](../images/font-previews/terminus-bold.png) | ![Terminus TTF Bold 2.66](../images/font-previews/terminus-bold-266.png) |
| VT323 | `VT323-Regular.ttf` | - | 48+32 / 56+40 | Modelled on the DEC VT320 terminal. Narrow, so long strings fit. | ![VT323](../images/font-previews/vt323.png) | ![VT323 2.66](../images/font-previews/vt323-266.png) |
| Pixelify Sans | `PixelifySans.ttf` | - | 48+32 / 56+40 | Rounded pixel look with an ordinary sans skeleton. | ![Pixelify Sans](../images/font-previews/pixelify-sans.png) | ![Pixelify Sans 2.66](../images/font-previews/pixelify-sans-266.png) |
| Jersey 10 | `Jersey10-Regular.ttf` | - | 48+32 / 56+40 | Condensed pixel display face; good for large numbers. | ![Jersey 10](../images/font-previews/jersey-10.png) | ![Jersey 10 2.66](../images/font-previews/jersey-10-266.png) |

### What the previews show

- **Silkscreen, Press Start 2P and Tiny5** at multiples of 8 px are the only samples with no stair-stepping at all. Every stroke is a clean block. The trade-off is a deliberately retro look and, for Press Start 2P, very wide text.
- **Galmuri11** gives the same effect with Hangul support. Its diagonals are made of 4 px steps at size 48, which is inherent to an 11 px design scaled up.
- **B612, Atkinson Hyperlegible and DejaVu Sans** are the cleanest ordinary fonts. Stems are one uniform width and curves are smooth, because their hinting was written for exactly this kind of rendering. Liberation Sans is close behind and is the most space-efficient of the four.
- **Noto Sans KR** and the other Korean fonts are auto-hinted. They look fine at the sizes shown, but thin weights lose pixels on curves and the Ownglyph handwriting face breaks up.
- On the 2.66" canvas everything is slightly larger in pixels, which hides aliasing a little, but the physical pixel density of the two labels is similar so the visual result is close.

### Licenses

All new fonts are redistributable. The license texts are in [optional_fonts/licenses](../optional_fonts/licenses/).

| Fonts | License |
| --- | --- |
| Atkinson Hyperlegible, B612, Silkscreen, Press Start 2P, Tiny5, DotGothic16, VT323, Pixelify Sans, Jersey 10 | SIL Open Font License 1.1 |
| Liberation Sans | SIL Open Font License 1.1 |
| Terminus TTF | SIL Open Font License 1.1 |
| Galmuri | SIL Open Font License 1.1 |
| DejaVu Sans | Bitstream Vera license (free redistribution) |

### Sources

- [Atkinson Hyperlegible, Braille Institute](https://www.brailleinstitute.org/freefont/)
- [B612, the font family for aircraft cockpit screens](https://b612-font.com/)
- [DejaVu fonts](https://dejavu-fonts.github.io/)
- [Liberation fonts](https://github.com/liberationfonts/liberation-fonts)
- [Silkscreen on Google Fonts](https://fonts.google.com/specimen/Silkscreen)
- [Press Start 2P on Google Fonts](https://fonts.google.com/specimen/Press+Start+2P)
- [Tiny5 on Google Fonts](https://fonts.google.com/specimen/Tiny5)
- [DotGothic16 on Google Fonts](https://fonts.google.com/specimen/DotGothic16)
- [VT323 on Google Fonts](https://fonts.google.com/specimen/VT323)
- [Pixelify Sans on Google Fonts](https://fonts.google.com/specimen/Pixelify+Sans)
- [Jersey 10 on Google Fonts](https://fonts.google.com/specimen/Jersey+10)
- [Terminus TTF](https://files.ax86.net/terminus-ttf/)
- [Galmuri, Korean pixel font](https://github.com/quiple/galmuri)
- [Font hinting, Wikipedia](https://en.wikipedia.org/wiki/Font_hinting)
- [Font configuration, ArchWiki](https://wiki.archlinux.org/title/Font_configuration)
