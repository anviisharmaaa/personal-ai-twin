import type { Basis, CharacterProfile, Item } from "../lib/api";

// Text, not colour, carries how well-supported each point is.
const BASIS: Record<Basis, string> = {
  stated: "You said this",
  inferred: "Read from your details",
  context_dependent: "Depends on the situation",
};

type Ctx = CharacterProfile["context_tendencies"];
type Group = { label: string; items?: Item[]; quotes?: string[]; notes?: string[]; situations?: Ctx };
type Section = { title: string; groups: Group[] };

function sections(p: CharacterProfile): Section[] {
  return [
    { title: "At a glance", groups: [{ label: "Core character", items: p.core_traits }] },
    {
      title: "How they express themselves",
      groups: [
        { label: "Speaking style", items: p.speaking_style },
        { label: "Phrases they might use", quotes: p.typical_expressions },
        { label: "Warmth and expressiveness", items: p.warmth_and_expressiveness },
        { label: "Humour and playfulness", items: p.humour_and_playfulness },
      ],
    },
    {
      title: "How they relate to people",
      groups: [
        { label: "Relationships", items: p.relationships_and_social },
        { label: "When someone needs support", items: p.empathy_and_support },
        { label: "Directness and disagreement", items: p.directness_and_disagreement },
      ],
    },
    {
      title: "What matters to them",
      groups: [
        { label: "Values and motivations", items: p.values_and_motivations },
        { label: "Interests and habits", items: p.interests_and_habits },
      ],
    },
    {
      title: "How they respond in different situations",
      groups: [
        { label: "Depending on the situation", situations: p.context_tendencies },
        { label: "Typical patterns", items: p.response_patterns },
      ],
    },
    {
      title: "Communication tendencies",
      groups: [
        { label: "Preferences", items: p.communication_preferences },
        { label: "Guidance for an AI representation", notes: p.behavioural_guidance },
      ],
    },
    {
      title: "Boundaries and open questions",
      groups: [
        { label: "Boundaries and topics to handle with care", items: p.boundaries_and_careful_topics },
        { label: "Not clear from the description", notes: p.uncertainties },
      ],
    },
  ];
}

const slug = (t: string) => `sec-${t.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
const has = (g: Group) => Boolean(g.items?.length || g.quotes?.length || g.notes?.length || g.situations?.length);

/** Renders the interpretation as plain text only (never as HTML), and omits anything the description didn't support. */
export function CharacterProfileView({ profile }: { profile: CharacterProfile }) {
  const secs = sections(profile)
    .map((s) => ({ ...s, groups: s.groups.filter(has) }))
    .filter((s) => s.groups.length > 0);

  return (
    <div className="space-y-10">
      {profile.summary && (
        <p className="max-w-[62ch] text-lg leading-relaxed">{profile.summary}</p>
      )}

      {secs.map((s) => (
        <section key={s.title} aria-labelledby={slug(s.title)} className="border-t border-border pt-6">
          <h3 id={slug(s.title)} className="text-base font-semibold">{s.title}</h3>
          <div className="mt-4 space-y-6">
            {s.groups.map((g) => (
              <div key={g.label}>
                <h4 className="text-sm font-medium text-muted">{g.label}</h4>
                {g.situations && (
                  <dl className="mt-2 space-y-3">
                    {g.situations.map((c, i) => (
                      <div key={i} className="max-w-[62ch]">
                        <dt className="font-medium">{c.context}</dt>
                        <dd>{c.tendency} <span className="whitespace-nowrap text-xs text-muted">· {BASIS[c.basis]}</span></dd>
                        {c.evidence && <dd className="mt-0.5 text-sm text-muted">From your description: “{c.evidence}”</dd>}
                      </div>
                    ))}
                  </dl>
                )}
                <ul className="mt-2 space-y-3">
                  {g.items?.map((it, i) => (
                    <li key={i} className="max-w-[62ch]">
                      <span>{it.text}</span>{" "}
                      <span className="whitespace-nowrap text-xs text-muted">· {BASIS[it.basis]}</span>
                    </li>
                  ))}
                  {g.quotes?.map((q, i) => <li key={i} className="max-w-[62ch] italic">“{q}”</li>)}
                  {g.notes?.map((n, i) => <li key={i} className="max-w-[62ch]">{n}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </section>
      ))}

    </div>
  );
}
