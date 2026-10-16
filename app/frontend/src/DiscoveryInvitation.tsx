import { ArrowRight, BookOpen, GitBranch } from "lucide-react";
import s from "./Discovery.module.css";

export function DiscoveryInvitation({
  onNavigate,
}: {
  onNavigate: (view: string) => void;
}) {
  return (
    <section className={s.invitation} aria-label="Discover the experiment loop">
      <div>
        <span className={s.eyebrow}>BEYOND THE PIPETTE</span>
        <h2>Learn to design the experiment.</h2>
        <p>
          Start with a question. Prepare samples, measure what matters, and
          decide what to try next.
        </p>
        <button className={s.primary} onClick={() => onNavigate("discovery")}>
          Open discovery studio <ArrowRight size={17} />
        </button>
      </div>
      <div className={s.invitePaths}>
        <div className={s.miniLoop}>
          <span>01 Prepare</span>
          <ArrowRight size={16} />
          <span>02 Test</span>
          <ArrowRight size={16} />
          <span>03 Optimize</span>
        </div>
        <button onClick={() => onNavigate("marketplace")}>
          <BookOpen size={20} />
          <span>
            <strong>Workflow marketplace</strong>
            <small>Six research papers. Six ways to think about a lab.</small>
          </span>
          <ArrowRight size={17} />
        </button>
        <button onClick={() => onNavigate("connector")}>
          <GitBranch size={20} />
          <span>
            <strong>Inside the Flex connector</strong>
            <small>Follow an action from software to the device API.</small>
          </span>
          <ArrowRight size={17} />
        </button>
      </div>
    </section>
  );
}
