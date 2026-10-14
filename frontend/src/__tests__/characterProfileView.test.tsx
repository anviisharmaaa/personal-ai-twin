import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CharacterProfileView } from "../components/CharacterProfileView";
import type { CharacterProfile } from "../lib/api";

// Test data only; not real model output.
const empty: CharacterProfile = {
  summary: "", core_traits: [], speaking_style: [], typical_expressions: [], warmth_and_expressiveness: [],
  humour_and_playfulness: [], empathy_and_support: [], directness_and_disagreement: [], values_and_motivations: [],
  relationships_and_social: [], interests_and_habits: [], communication_preferences: [],
  boundaries_and_careful_topics: [], context_tendencies: [], response_patterns: [], behavioural_guidance: [],
  uncertainties: [],
};

describe("CharacterProfileView", () => {
  it("renders nothing for areas the description did not cover", () => {
    render(<CharacterProfileView profile={{ ...empty, summary: "Quiet and kind." }} />);
    expect(screen.getByText("Quiet and kind.")).toBeTruthy();
    expect(screen.queryAllByRole("heading")).toHaveLength(0);
  });

  it("labels how well supported each point is in words, and shows situational behaviour", () => {
    render(
      <CharacterProfileView
        profile={{
          ...empty,
          core_traits: [{ text: "Loyal", basis: "stated" }],
          context_tendencies: [{ context: "With strangers", tendency: "Reserved", basis: "context_dependent" }],
        }}
      />,
    );
    expect(screen.getByText(/You said this/)).toBeTruthy();
    expect(screen.getByText("With strangers")).toBeTruthy();
    expect(screen.getByText(/Depends on the situation/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "How they respond in different situations" })).toBeTruthy();
  });

  it("treats model text as plain text, never HTML", () => {
    const { container } = render(
      <CharacterProfileView profile={{ ...empty, summary: '<img src=x onerror="alert(1)">hi' }} />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img");
  });
});
