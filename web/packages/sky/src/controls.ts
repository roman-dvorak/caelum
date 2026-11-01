import { SKY_LAYERS } from './draw.ts'

/** A slider in the sky settings menu: `settings[key]` is shown as `value * factor` on the slider. */
export interface SkySliderSpec {
  key: 'maxMagnitude' | 'symbolScale' | 'opacity'
  min: number
  max: number
  step: number
  factor: number
  /** Decimals of the number shown in the label. */
  decimals: number
  /** The label shows `value * labelFactor`. */
  labelFactor: number
}

/** The sliders of the sky settings menu, in order. Every menu is drawn from this, so a new one is added once. */
export const SKY_SLIDERS: readonly SkySliderSpec[] = [
  { key: 'maxMagnitude', min: 0, max: 5, step: 0.5, factor: 1, decimals: 1, labelFactor: 1 },
  { key: 'symbolScale', min: 50, max: 300, step: 10, factor: 100, decimals: 0, labelFactor: 100 },
  { key: 'opacity', min: 10, max: 100, step: 5, factor: 100, decimals: 0, labelFactor: 100 },
]

export type SkyLocale = 'en' | 'cs'

export interface SkyText {
  /** The switch and the title of the folded menu. */
  sky: string
  options: string
  layers: Record<(typeof SKY_LAYERS)[number], string>
  /** Slider labels with a `{value}` placeholder. */
  sliders: Record<SkySliderSpec['key'], string>
}

const TEXT: Record<SkyLocale, SkyText> = {
  en: {
    sky: 'Sky',
    options: 'What to draw',
    layers: {
      outline: 'Lens outline & centre',
      grid: 'Horizon & altitude rings',
      ecliptic: 'Ecliptic',
      radec: 'RA / Dec circles',
      constellations: 'Constellation lines',
      stars: 'Stars',
      planets: 'Sun, Moon & planets',
      compass: 'Compass',
    },
    sliders: {
      maxMagnitude: 'Faintest star: mag {value}',
      symbolScale: 'Symbol size: {value} %',
      opacity: 'Opacity: {value} %',
    },
  },
  cs: {
    sky: 'Obloha',
    options: 'Co kreslit',
    layers: {
      outline: 'Obrys čočky a střed',
      grid: 'Horizont a kruhy výšky',
      ecliptic: 'Ekliptika',
      radec: 'Kružnice RA / Dec',
      constellations: 'Čáry souhvězdí',
      stars: 'Hvězdy',
      planets: 'Slunce, Měsíc a planety',
      compass: 'Světové strany',
    },
    sliders: {
      maxMagnitude: 'Nejslabší hvězda: mag {value}',
      symbolScale: 'Velikost symbolů: {value} %',
      opacity: 'Průhlednost: {value} %',
    },
  },
}

/** The menu's texts in `locale` (English for anything else). */
export function skyText(locale: string): SkyText {
  return TEXT[locale as SkyLocale] ?? TEXT.en
}

/** A slider's label with the current value filled in. */
export function skySliderLabel(spec: SkySliderSpec, text: SkyText, value: number): string {
  return text.sliders[spec.key].replace('{value}', (value * spec.labelFactor).toFixed(spec.decimals))
}
