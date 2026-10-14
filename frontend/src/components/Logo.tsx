import { LOGO_PLATES, type LogoVariant } from "../lib/brand";

type Props = { variant?: LogoVariant; height?: number; padded?: boolean; className?: string };

/** The approved logo artwork on its prescribed reciprocal plate. Never stretched or recoloured. */
export function Logo({ variant = "gold-on-maroon", height = 32, padded = true, className = "" }: Props) {
  const v = LOGO_PLATES[variant];
  return (
    <span
      data-testid="logo-plate"
      data-variant={variant}
      className={`inline-flex items-center rounded-[10px] ${padded ? "px-3 py-2" : ""} ${className}`}
      style={{ backgroundColor: v.plate }}
    >
      <img src={v.src} alt="Madhuora" style={{ height, width: "auto" }} draggable={false} />
    </span>
  );
}
