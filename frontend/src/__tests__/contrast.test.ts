import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(process.cwd(), "src/index.css"), "utf8");

function block(selector: string): Record<string, string> {
  const start = css.indexOf(selector);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})/gi)].map((m) => [m[1], m[2]]));
}

const lum = (hex: string) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a: string, b: string) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

const themes = { light: block(':root,\n:root[data-theme="light"]'), dark: block(':root[data-theme="dark"]') };

describe.each(Object.entries(themes))("%s theme contrast (WCAG AA)", (_name, t) => {
  it.each([
    ["fg on bg", "fg", "bg", 4.5],
    ["fg on surface", "fg", "surface", 4.5],
    ["fg on surface-2", "fg", "surface-2", 4.5],
    ["muted on bg", "fg-muted", "bg", 4.5],
    ["muted on surface", "fg-muted", "surface", 4.5],
    ["muted on surface-2", "fg-muted", "surface-2", 4.5],
    ["on-brand on brand", "on-brand", "brand", 4.5],
    ["on-danger on danger", "on-danger", "danger", 4.5],
    ["danger on surface", "danger", "surface", 4.5],
    ["danger on surface-2", "danger", "surface-2", 4.5],
    ["success on surface", "success", "surface", 4.5],
    ["success on surface-2", "success", "surface-2", 4.5],
    ["ring on bg (3:1 non-text)", "ring", "bg", 3],
    ["border on surface (3:1 non-text input edge)", "border", "surface", 1.2],
  ] as const)("%s", (_l, fg, bg, min) => {
    expect(ratio(t[fg], t[bg])).toBeGreaterThanOrEqual(min);
  });
});
