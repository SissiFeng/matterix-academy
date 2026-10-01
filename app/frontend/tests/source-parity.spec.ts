import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { developmentSources } from "../src/connectorDevelopmentSources";

test("developer excerpts match the pinned source evidence byte for byte", () => {
  const record = JSON.parse(
    readFileSync(
      new URL(
        "../../../docs/briefs/connector-development-source.json",
        import.meta.url,
      ),
      "utf8",
    ),
  );
  expect(developmentSources).toEqual(record.excerpts);
  for (const excerpt of developmentSources) {
    expect(excerpt.url).toContain(
      `/blob/${record.commit}/${excerpt.path}#L${excerpt.start}-L${excerpt.end}`,
    );
  }
});
