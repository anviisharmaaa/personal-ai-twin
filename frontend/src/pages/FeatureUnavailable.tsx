import { Link } from "react-router-dom";
import { Card, Chip } from "../components/ui";

type Props = { title: string; lead: string; will: string[]; meanwhile?: { to: string; label: string } };

/** Honest placeholder: states plainly that the capability does not exist yet. */
export function FeatureUnavailable({ title, lead, will, meanwhile }: Props) {
  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        <Chip tone="soon">Not available yet</Chip>
      </div>
      <p className="mt-3 max-w-xl text-muted">{lead}</p>
      <Card className="mt-8">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted">What this will do</h2>
        <ul className="mt-3 list-disc space-y-2 pl-5 text-sm">{will.map((w) => <li key={w}>{w}</li>)}</ul>
        <p className="mt-5 text-sm text-muted">Nothing here is active, and nothing about your twin is being collected for this feature.</p>
        {meanwhile && <Link to={meanwhile.to} className="mt-4 inline-block text-sm font-medium text-accent underline underline-offset-4">{meanwhile.label}</Link>}
      </Card>
    </div>
  );
}
