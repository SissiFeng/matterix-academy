import type { Session } from "./types";

export const LEARNING_LEVELS = [
  {
    id: "beginner",
    title: "Beginner",
    heading: "Your first workflow.",
    goal: "Meet the instrument, transfer liquid and explain what changed.",
  },
  {
    id: "intermediate",
    title: "Intermediate",
    heading: "Design a complete experiment.",
    goal: "Review a method, connect its steps and plan the workcell around it.",
  },
  {
    id: "advanced",
    title: "Advanced",
    heading: "Understand the connected lab.",
    goal: "Explore command contracts, connectors and device readiness.",
  },
] as const;
export type LearningLevel = (typeof LEARNING_LEVELS)[number]["id"];

export function learningLevelFromPath(path: string): LearningLevel {
  const [view, level] = path.replace(/^#?\/?/, "").split("/");
  return view === "learn" && LEARNING_LEVELS.some((item) => item.id === level)
    ? (level as LearningLevel)
    : "beginner";
}

export function latestCourseSession(sessions: Session[], course: string) {
  return sessions
    .filter((item) => item.experiment.course_id === course)
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
}

export function learningStatus(session: Session | undefined): string {
  if (!session) return "Not started";
  if (session.experiment.course_id === "flex-first-transfer") {
    if (
      session.lesson_outcome?.practice_completed &&
      session.lesson_outcome.understanding_demonstrated
    )
      return "Practice and understanding complete";
    if (session.status === "completed")
      return "Practice complete · reflection remaining";
  } else if (
    session.status === "completed" &&
    session.assessment?.passed &&
    session.assessment.scope === "lesson-goal"
  ) {
    return "Teaching goal reached";
  }
  return `${session.cursor} / ${session.experiment.actions.length} steps · ${session.status}`;
}
