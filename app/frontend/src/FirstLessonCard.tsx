import { ArrowRight, ChevronRight } from "lucide-react";
import { PHASES } from "./learningContent";
import s from "./LearningLab.module.css";

export function FirstLessonCard({
  onStart,
  resume,
}: {
  onStart: () => void;
  resume: boolean;
}) {
  return (
    <section className={s.lessonCard}>
      <div>
        <h2>Learn automated pipetting.</h2>
        <p>From finding tips and wells to explaining a 100 µL transfer.</p>
        <button className={s.primary} onClick={onStart}>
          {resume ? "Continue my Flex lesson" : "Start learning Flex"}
          <ArrowRight size={18} />
        </button>
      </div>
      <div className={s.lessonIndex}>
        {PHASES.map((p, i) => (
          <div key={p.id}>
            <span>0{i + 1}</span>
            <div>
              <strong>{p.title}</strong>
              <small>{p.detail}</small>
            </div>
            <ChevronRight size={15} />
          </div>
        ))}
      </div>
    </section>
  );
}
