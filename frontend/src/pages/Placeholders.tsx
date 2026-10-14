import { FeatureUnavailable } from "./FeatureUnavailable";

export const Conversations = () => (
  <FeatureUnavailable title="Conversations" lead="Talk with your twin in text, with replies that stream in as they’re written."
    will={["Persistent conversations you can revisit or delete", "Stop and retry controls", "Subtle notes when an approved memory shaped a reply"]}
    meanwhile={{ to: "/app/studio", label: "Refine your twin in Twin Studio" }} />
);
export const Memories = () => (
  <FeatureUnavailable title="Memories" lead="Stories and facts your twin may draw on — only ever after you approve them."
    will={["Import notes and documents as source material", "Review, edit, approve or reject every proposed memory", "Pin, search and delete memories at any time"]} />
);
export const Voice = () => (
  <FeatureUnavailable title="Voice" lead="Send a voice message, review the transcript, then get a reply you can read or hear."
    will={["Record or upload audio", "Edit the transcript before anything is sent", "Spoken replies you can turn off"]} />
);
export const Automations = () => (
  <FeatureUnavailable title="Automations" lead="Gentle, scheduled messages that you control completely."
    will={["One-time and recurring messages", "Quiet hours and a daily limit", "Pause, edit or cancel at any time"]} />
);
