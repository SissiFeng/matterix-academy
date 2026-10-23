import type { Page } from "@playwright/test";
export type JourneyActor = { page: Page; mutations: number; label: string };
export type JourneyReport = {
  checks: Record<string, boolean>;
  sessions: {
    learner: string;
    id: string;
    evidence: string;
    steps: number;
    runs?: number;
  }[];
};
export type JourneyOptions = {
  read: (actor: JourneyActor, endpoint: string) => Promise<unknown>;
  report: JourneyReport;
  runId?: string;
};
export function courseJourney(
  actor: JourneyActor,
  options: JourneyOptions,
): Promise<unknown>;
export function dilutionJourney(
  actor: JourneyActor,
  options: JourneyOptions & { runId: string },
): Promise<unknown>;
export function firstTransferJourney(
  actor: JourneyActor,
  options: JourneyOptions,
): Promise<unknown>;
