// Colour science for the visual language (PRD 16.3, VIS-5): OKLab, WCAG contrast and colour-vision-deficiency simulation.

export type RGB = [number, number, number];

export const toLinear = (c: number) => {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
};
export const toSrgb = (v: number) => {
  const c = Math.max(0, Math.min(1, v));
  return Math.round(255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * Math.pow(c, 1 / 2.4) - 0.055));
};

/** Parses #rgb, #rrggbb, rgb(r g b) and rgb(r, g, b), ignoring alpha. */
export function parseColor(input: string): RGB {
  const s = input.trim();
  if (s.startsWith('#')) {
    const hex = s.length === 4 ? s.slice(1).split('').map((c) => c + c).join('') : s.slice(1, 7);
    return [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16)) as RGB;
  }
  const nums = s.match(/[\d.]+/g)?.map(Number) ?? [0, 0, 0];
  return [nums[0], nums[1], nums[2]];
}

export const hex = ([r, g, b]: RGB) => `#${[r, g, b].map((v) => Math.round(v).toString(16).padStart(2, '0')).join('')}`;

export function luminance(rgb: RGB): number {
  const [r, g, b] = rgb.map(toLinear);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG 2 contrast ratio. */
export function contrast(a: RGB, b: RGB): number {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

// OKLab (Björn Ottosson, 2020).
export function toOklab(rgb: RGB): [number, number, number] {
  const [r, g, b] = rgb.map(toLinear);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s, 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s, 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s];
}

export function fromOklab([L, a, b]: [number, number, number]): RGB {
  const l = Math.pow(L + 0.3963377774 * a + 0.2158037573 * b, 3);
  const m = Math.pow(L - 0.1055613458 * a - 0.0638541728 * b, 3);
  const s = Math.pow(L - 0.0894841775 * a - 1.291485548 * b, 3);
  return [
    toSrgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
    toSrgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
    toSrgb(-0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s),
  ];
}

/** Perceptual distance in OKLab; about 0.02 is just noticeable, 0.1 is clearly different. */
export function deltaE(a: RGB, b: RGB): number {
  const [l1, a1, b1] = toOklab(a);
  const [l2, a2, b2] = toOklab(b);
  return Math.hypot(l1 - l2, a1 - a2, b1 - b2);
}

export type Vision = 'typical' | 'deuteranopia' | 'protanopia' | 'tritanopia';
export const VISIONS: readonly Vision[] = ['typical', 'deuteranopia', 'protanopia', 'tritanopia'];

// Machado, Oliveira and Fernandes (2009), full severity, applied in linear RGB.
const CVD: Record<Vision, number[][]> = {
  typical: [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
  ],
  deuteranopia: [
    [0.367322, 0.860646, -0.227968],
    [0.280085, 0.672501, 0.047413],
    [-0.01182, 0.04294, 0.968881],
  ],
  protanopia: [
    [0.152286, 1.052583, -0.204868],
    [0.114503, 0.786281, 0.099216],
    [-0.003882, -0.048116, 1.051998],
  ],
  tritanopia: [
    [1.255528, -0.076749, -0.178779],
    [-0.078411, 0.930809, 0.147602],
    [0.004733, 0.691367, 0.3039],
  ],
};

export function simulate(rgb: RGB, vision: Vision): RGB {
  const lin = rgb.map(toLinear);
  return CVD[vision].map((row) => toSrgb(row[0] * lin[0] + row[1] * lin[1] + row[2] * lin[2])) as RGB;
}

/** Moves a colour's OKLab lightness, keeping hue, until it reaches `target` contrast against `against`. */
export function adjustForContrast(color: RGB, against: RGB, target: number): RGB {
  if (contrast(color, against) >= target) return color;
  const lighter = luminance(against) < 0.18;
  const lab = toOklab(color);
  let out = color;
  for (let i = 1; i <= 40; i++) {
    const L = Math.max(0, Math.min(1, lab[0] + (lighter ? 1 : -1) * i * 0.02));
    // Pull chroma in a little as lightness moves, so the colour stays inside sRGB.
    const k = Math.max(0.4, 1 - i * 0.012);
    out = fromOklab([L, lab[1] * k, lab[2] * k]);
    if (contrast(out, against) >= target) break;
  }
  return out;
}

/** Reads a token's resolved colour for a theme, from a probe element carrying data-theme. */
export function readToken(name: string, el: Element = document.documentElement): string {
  return getComputedStyle(el).getPropertyValue(name).trim();
}
