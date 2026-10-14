import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Logo } from "../components/Logo";
import { LOGO_PLATES } from "../lib/brand";

describe("reciprocal signature logo rule", () => {
  it("maroon wordmark only on gold, gold wordmark only on maroon", () => {
    expect(LOGO_PLATES["maroon-on-gold"]).toMatchObject({ wordmark: "#68283b", plate: "#e9c878" });
    expect(LOGO_PLATES["gold-on-maroon"]).toMatchObject({ wordmark: "#e9c878", plate: "#68283b" });
  });
  it("renders the approved artwork on the opposite-colour plate without stretching", () => {
    render(<Logo variant="gold-on-maroon" height={30} />);
    const plate = screen.getByTestId("logo-plate");
    expect(plate).toHaveStyle({ backgroundColor: "#68283b" });
    const img = screen.getByAltText("Madhuora");
    expect(img).toHaveAttribute("src", "/brand/madhuora-logo-gold.png");
    expect(img.style.width).toBe("auto");
  });
});
