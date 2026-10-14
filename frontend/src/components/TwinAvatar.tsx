import type { Twin } from "../lib/api";

const BACKDROP: Record<string, string> = {
  ivory: "#faf5ed", wine: "#211016", maroon: "#68283b", gold: "#e9c878",
};
const FRAMING: Record<string, string> = { close: "scale-125", bust: "scale-100", wide: "scale-90" };

type Props = { twin: Twin | null; size?: number; orbit?: boolean };

/** Portrait (not an animated avatar). The orbit ring is decoration only and stops under reduced-motion. */
export function TwinAvatar({ twin, size = 160, orbit = true }: Props) {
  const bg = BACKDROP[twin?.appearance.background ?? "wine"] ?? BACKDROP.wine;
  const initial = (twin?.name ?? "?").trim().charAt(0).toUpperCase();
  const light = twin?.appearance.lighting;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      {orbit && (
        <>
          <div className="absolute -inset-3 rounded-full border border-border" aria-hidden />
          <div className="absolute -inset-3 rounded-full" style={{ animation: "orbit 24s linear infinite" }} aria-hidden>
            <span className="absolute left-1/2 top-0 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent" />
          </div>
          <div className="absolute -inset-7 rounded-full" style={{ animation: "orbit 40s linear infinite reverse" }} aria-hidden>
            <span className="absolute bottom-0 left-1/2 size-1.5 -translate-x-1/2 translate-y-1/2 rounded-full bg-accent/60" />
          </div>
        </>
      )}
      <div className="relative size-full overflow-hidden rounded-full border border-border" style={{ background: bg }}>
        {twin?.portrait_url ? (
          <img src={twin.portrait_url} alt={`Portrait of ${twin.name}`}
            className={`size-full object-cover ${FRAMING[twin.appearance.framing ?? "bust"] ?? ""}`} />
        ) : (
          <div className="grid size-full place-items-center font-semibold" style={{ fontSize: size / 3, color: bg === "#faf5ed" || bg === "#e9c878" ? "#68283b" : "#e9c878" }}>
            {initial}
          </div>
        )}
        {light === "warm" && <div className="absolute inset-0" style={{ background: "linear-gradient(135deg, rgba(233,200,120,.28), transparent 60%)" }} />}
        {light === "soft" && <div className="absolute inset-0" style={{ background: "radial-gradient(circle at 30% 20%, rgba(255,255,255,.22), transparent 60%)" }} />}
      </div>
    </div>
  );
}
