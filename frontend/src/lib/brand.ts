/**
 * Mandatory reciprocal rule for the signature wordmark:
 *   maroon wordmark (#68283B) sits ONLY on antique gold (#E9C878), and
 *   gold wordmark sits ONLY on deep maroon.
 * The wordmark is therefore always rendered inside a "plate" of the opposite colour.
 */
export const LOGO_PLATES = {
  "maroon-on-gold": { src: "/brand/madhuora-logo-maroon.png", plate: "#e9c878", wordmark: "#68283b" },
  "gold-on-maroon": { src: "/brand/madhuora-logo-gold.png", plate: "#68283b", wordmark: "#e9c878" },
} as const;

export type LogoVariant = keyof typeof LOGO_PLATES;
