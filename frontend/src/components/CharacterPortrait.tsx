/** A character's portrait (or a monogram when none was added). Decorative-safe: the name is always shown next to it. */
export function CharacterPortrait({ name, url, size = 56 }: { name: string; url: string | null; size?: number }) {
  const initial = (name || "?").trim().charAt(0).toUpperCase();
  return (
    <span className="relative inline-block shrink-0 overflow-hidden rounded-full border border-accent/60"
      style={{ width: size, height: size, background: "#68283b", color: "#e9c878" }}>
      {url
        ? <img src={url} alt={`Portrait of ${name}`} className="size-full object-cover" />
        : <span className="grid size-full place-items-center font-semibold" style={{ fontSize: size / 2.4 }} aria-hidden>{initial}</span>}
    </span>
  );
}
