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
        <span className={s.eyebrow}>
          START HERE / BUILD ON YOUR MANUAL LAB SKILLS
        </span>
        <h2>
          Meet your first
          <br />
          <em>automated pipetting workstation.</em>
        </h2>
        <p>
          From finding tips and wells to explaining a 100 µL transfer.
          <br />
          Explore the equipment, predict the result, then try it yourself.
        </p>
        <button className={s.primary} onClick={onStart}>
          {resume ? "Continue my Flex lesson" : "Start learning Flex"}
          <ArrowRight size={18} />
        </button>
        <small>5 learning stages · Guided practice · No coding required</small>
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
