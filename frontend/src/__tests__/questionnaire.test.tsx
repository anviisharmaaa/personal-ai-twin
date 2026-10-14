import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { Questionnaire, type Answers } from "../components/Questionnaire";
import type { Question } from "../lib/api";

const qs: Question[] = [
  { id: "tone", prompt: "Tone?", multi: false, options: ["warm", "calm"] },
  { id: "values", prompt: "Values?", multi: true, max: 2, options: ["family", "honesty", "faith"] },
];

function Harness() {
  const [a, setA] = useState<Answers>({});
  return (<><Questionnaire questions={qs} value={a} onChange={setA} /><output data-testid="o">{JSON.stringify(a)}</output></>);
}

describe("Questionnaire", () => {
  it("single choice toggles and offers Not sure", () => {
    render(<Harness />);
    fireEvent.click(screen.getAllByRole("radio", { name: "Warm" })[0]);
    expect(screen.getByTestId("o")).toHaveTextContent('"tone":"warm"');
    fireEvent.click(screen.getAllByRole("radio", { name: "Not sure" })[0]);
    expect(screen.getByTestId("o")).toHaveTextContent('"tone":"not_sure"');
    fireEvent.click(screen.getAllByRole("radio", { name: "Not sure" })[0]);
    expect(screen.getByTestId("o")).toHaveTextContent("{}");
  });
  it("multi choice enforces the maximum and Not sure clears the rest", () => {
    render(<Harness />);
    for (const n of ["Family", "Honesty", "Faith"]) fireEvent.click(screen.getByRole("checkbox", { name: n }));
    expect(screen.getByTestId("o")).toHaveTextContent('"values":["family","honesty"]');
    fireEvent.click(screen.getAllByRole("checkbox", { name: "Not sure" })[0]);
    expect(screen.getByTestId("o")).toHaveTextContent('"values":["not_sure"]');
  });
});
