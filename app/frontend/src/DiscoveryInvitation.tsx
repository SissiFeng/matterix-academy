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
        <h2>Design an experiment.</h2>
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
          </span>
          <ArrowRight size={17} />
        </button>
        <button onClick={() => onNavigate("connector")}>
          <GitBranch size={20} />
          <span>
            <strong>Inside the Flex connector</strong>
          </span>
          <ArrowRight size={17} />
        </button>
      </div>
    </section>
  );
}
