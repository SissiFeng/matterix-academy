import Pictogram from "./Pictogram";
import s from "./PageStory.module.css";

type Step = [art: string, caption: string];

/** What a page is for, as three drawn steps in place of a paragraph. */
export const stories: Record<string, Step[]> = {
  instruments: [
    ["sim", "Watch a step"],
    ["marketplace", "Change it"],
    ["learn", "Build your own"],
  ],
  sim: [
    ["marketplace", "Your experiment"],
    ["instruments", "Virtual robot runs it"],
    ["caught", "Mistakes show early"],
  ],
  groups: [
    ["groups", "Share"],
    ["compare", "Compare"],
    ["agreed", "Agree on one"],
  ],
  discovery: [
    ["samples", "Prepare"],
    ["measure", "Measure"],
    ["decide", "Decide what is next"],
  ],
  onboard: [
    ["onboard", "Your instrument"],
    ["twin", "Its teaching twin"],
    ["sim", "Practise safely"],
  ],
  twin: [
    ["marketplace", "Run a workflow"],
    ["twin", "The twin records it"],
    ["compare", "Compare with your plan"],
  ],
  readiness: [
    ["sim", "Practised workflow"],
    ["readiness", "Pass the checks"],
    ["instruments", "Real run"],
  ],
  runs: [
    ["runs", "Pick a run"],
    ["learn", "Step through it"],
    ["caught", "See where it stopped"],
  ],
};

export default function PageStory({ page }: { page: string }) {
  const steps = stories[page];
  if (!steps) return null;
  return (
    <ol className={s.story} aria-label="What this page is for">
      {steps.map(([art, caption]) => (
        <li key={caption}>
          <span className={s.tile}>
            <Pictogram name={art} />
          </span>
          <strong>{caption}</strong>
        </li>
      ))}
    </ol>
  );
}
