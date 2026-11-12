import { useEffect, useState } from "react";
import { ArrowRight, GraduationCap, Search } from "lucide-react";
import { api } from "./api";
import type { LibraryEntry, LibraryResults } from "./instrumentTypes";
import type { StoryInstrument } from "./instrumentStoriesContent";
import s from "./InstrumentStories.module.css";

/** Handed to Plan a workcell so its library search opens on the same words. */
export const LIBRARY_QUERY_KEY = "academy-library-query";

/** "Onboard me on …": a lesson when there is one, else a twin in Plan a workcell. */
export default function LessonSearch({
  onLesson,
}: {
  onLesson: (instrument: StoryInstrument) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<LibraryEntry[] | null>(null);
  useEffect(() => {
    const words = query.trim();
    if (words.length < 2) return setResults(null);
    let alive = true;
    const timer = window.setTimeout(async () => {
      try {
        const found = await api<LibraryResults>(
          `/twins/library?q=${encodeURIComponent(words)}`,
        );
        if (alive) setResults(found.results.slice(0, 5));
      } catch {
        if (alive) setResults([]);
      }
    }, 200);
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [query]);

  const plan = () => {
    try {
      sessionStorage.setItem(LIBRARY_QUERY_KEY, query.trim());
    } catch {
      // The plan page then opens on the featured list.
    }
    window.location.hash = "#/plan/instruments";
  };

  return (
    <div className={s.lessonSearch}>
      <label className={s.lessonField}>
        <Search size={16} aria-hidden />
        <input
          type="search"
          value={query}
          placeholder="Find your instrument"
          aria-label="Find an instrument to learn"
          maxLength={80}
          onChange={(e) => setQuery(e.target.value)}
        />
      </label>
      {results && (
        <ul className={s.lessonResults} aria-label="Instruments found">
          {results.map((entry) => (
            <li key={`${entry.collection}:${entry.id}`}>
              <span>
                <strong>{entry.name}</strong>
                <small>{entry.label}</small>
              </span>
              {entry.lesson ? (
                <button
                  type="button"
                  onClick={() => {
                    onLesson(entry.lesson!);
                    setQuery("");
                  }}
                >
                  <GraduationCap size={14} /> Lesson
                </button>
              ) : (
                <button type="button" onClick={plan}>
                  Build its twin <ArrowRight size={14} />
                </button>
              )}
            </li>
          ))}
          {results.length === 0 && (
            <li>
              <span>Not in the library yet.</span>
              <button type="button" onClick={plan}>
                Photograph it <ArrowRight size={14} />
              </button>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
