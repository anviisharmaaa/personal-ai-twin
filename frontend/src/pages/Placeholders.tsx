import { FeatureUnavailable } from "./FeatureUnavailable";

export const Voice = () => (
  <FeatureUnavailable title="Voice" lead="Send a voice message, review the transcript, then get a reply you can read or hear."
    will={["Record or upload audio", "Edit the transcript before anything is sent", "Spoken replies you can turn off"]} />
);
export const Automations = () => (
  <FeatureUnavailable title="Automations" lead="Gentle, scheduled messages that you control completely."
    will={["One-time and recurring messages", "Quiet hours and a daily limit", "Pause, edit or cancel at any time"]} />
);
