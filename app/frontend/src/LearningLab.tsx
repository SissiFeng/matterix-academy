import { useCallback, useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  FlaskConical,
  Monitor,
  Pause,
  Play,
  RotateCcw,
  SkipForward,
  WifiOff,
} from "lucide-react";
import { api, json } from "./api";
import type { LearningProgress, Session } from "./types";
import {
  EMPTY_LEARNING,
  EQUIPMENT,
  PHASES,
  PREPARATION,
  firstTransfer,
  stepExplanation,
} from "./learningContent";
import type { EquipmentId } from "./learningContent";
import FlexDiagram from "./FlexDiagram";
import s from "./LearningLab.module.css";

const number = (value: number) => Number(value.toFixed(2)).toLocaleString();
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
        <span className={s.eyebrow}>START HERE / 从你的手动实验经验出发</span>
        <h2>
          认识你的第一台
          <br />
          <em>自动化移液工作站。</em>
        </h2>
        <p>
          从找到吸头和目标孔，到解释一次 100 µL 转移。
          <br />
          先认识，再预测，最后亲手试一次。
        </p>
        <button className={s.primary} onClick={onStart}>
          {resume ? "继续我的入门课程" : "开始 Flex 入门"}
          <ArrowRight size={18} />
        </button>
        <small>5 个学习环节 · 中文引导 · 无需编程</small>
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

function RemoteView() {
  const [status, setStatus] = useState<{
    state: string;
    message: string;
  } | null>(null);
  const [busy, setBusy] = useState(false);
  const active = useRef(true);
  const check = useCallback(async () => {
    setBusy(true);
    try {
      const next = await api<{ state: string; message: string }>(
        "/remote/status",
      );
      if (active.current) setStatus(next);
    } catch {
      if (active.current)
        setStatus({
          state: "unreachable",
          message: "暂时无法检查连接，请稍后重试。",
        });
    } finally {
      if (active.current) setBusy(false);
    }
  }, []);
  useEffect(() => {
    active.current = true;
    check();
    return () => {
      active.current = false;
    };
  }, [check]);
  return (
    <div className={s.remote}>
      <Monitor size={38} />
      <span className={s.eyebrow}>REMOTE LAB / UBUNTU</span>
      <h3>真实 3D 仿真等待接入</h3>
      <p>{status?.message ?? "正在检查远程实验室连接…"}</p>
      <div className={s.connectionPath}>
        <span>你的浏览器</span>
        <ChevronRight size={14} />
        <span>课程平台</span>
        <ChevronRight size={14} />
        <span>Ubuntu 仿真</span>
      </div>
      <p>
        接通并验收后，这里展示 Matterix
        的真实画面。当前课程使用独立教学模型，你可以先认识设备、练习预测和动作顺序。
      </p>
      <button className={s.secondary} onClick={check} disabled={busy}>
        <RotateCcw size={15} />
        {busy ? "检查中…" : "重新检查连接"}
      </button>
      <small>学生无需 Ubuntu 账户。连接由实验室管理员配置。</small>
    </div>
  );
}

export default function LearningLab({
  session,
  onChange,
  onBack,
  onError,
  registerLeaveGuard,
}: {
  session: Session;
  onChange: (next: Session) => void;
  onBack: () => void;
  onError: (message: string) => void;
  registerLeaveGuard: (guard: (() => boolean) | null) => void;
}) {
  const learning = session.learning ?? EMPTY_LEARNING;
  const [selected, setSelected] = useState<EquipmentId>("pipette");
  const [view, setView] = useState<"diagram" | "remote">("diagram");
  const [busy, setBusy] = useState(false);
  const [auto, setAuto] = useState(false);
  const [prediction, setPrediction] = useState({
    source: learning.prediction?.source.toString() ?? "",
    tip: learning.prediction?.tip.toString() ?? "",
    target: learning.prediction?.target.toString() ?? "",
  });
  const [predictionMessage, setPredictionMessage] = useState("");
  const [predictionDirty, setPredictionDirty] = useState(false);
  const lock = useRef(false);
  const mounted = useRef(true);
  const current = useRef(session);
  current.current = session;
  const volume = session.experiment.transfer_volume ?? 100;
  const phase = learning.phase;
  const phaseIndex = PHASES.findIndex((p) => p.id === phase);
  const explanation = stepExplanation(
    session.cursor,
    volume,
    session.experiment.source_volume,
  );
  const evidence = EQUIPMENT[selected];
  const orientDone =
    session.readiness?.checks.find((c) => c.id === "orientation")?.passed ??
    false;
  const preparationDone =
    session.readiness?.checks.find((c) => c.id === "preparation")?.passed ??
    false;
  const predictionDone =
    session.readiness?.checks.find((c) => c.id === "prediction")?.passed ??
    false;
  const derivedDone = [
    orientDone,
    preparationDone,
    predictionDone,
    session.status === "completed",
    session.lesson_outcome?.practice_completed &&
      session.lesson_outcome?.understanding_demonstrated,
  ];
  const completed = derivedDone[4];
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    registerLeaveGuard(
      () => !predictionDirty || window.confirm("预测还未保存，确定离开吗？"),
    );
    const warn = (e: BeforeUnloadEvent) => {
      if (predictionDirty) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      registerLeaveGuard(null);
      window.removeEventListener("beforeunload", warn);
    };
  }, [predictionDirty, registerLeaveGuard]);
  const accept = useCallback(
    (next: Session) => {
      if (mounted.current) {
        current.current = next;
        onChange(next);
      }
    },
    [onChange],
  );
  const task = useCallback(
    async (action: () => Promise<Session>) => {
      if (lock.current || !mounted.current) return;
      lock.current = true;
      setBusy(true);
      try {
        const next = await action();
        accept(next);
        return next;
      } catch (e) {
        if (mounted.current) {
          setAuto(false);
          onError(e instanceof Error ? e.message : "操作未完成，请重试。");
          try {
            // A multi-request action may have saved its first step before failing.
            accept(await api<Session>(`/sessions/${current.current.id}`));
          } catch {
            /* Keep the original failure visible; never replay the mutation. */
          }
        }
      } finally {
        lock.current = false;
        if (mounted.current) setBusy(false);
      }
    },
    [accept, onError],
  );
  const saveProgress = (patch: Partial<LearningProgress>) =>
    task(() =>
      api<Session>(
        `/sessions/${current.current.id}/learning`,
        json(
          {
            version: current.current.version,
            learning: { ...current.current.learning, ...patch },
          },
          "PUT",
        ),
      ),
    );
  const changePhase = async (next: LearningProgress["phase"]) => {
    if (predictionDirty && !window.confirm("预测还未保存，确定切换步骤吗？"))
      return;
    const saved = await saveProgress({ phase: next });
    if (saved) {
      setPrediction({
        source: saved.learning?.prediction?.source.toString() ?? "",
        tip: saved.learning?.prediction?.tip.toString() ?? "",
        target: saved.learning?.prediction?.target.toString() ?? "",
      });
      setPredictionDirty(false);
      setPredictionMessage("");
      setView("diagram");
    }
  };
  const select = async (id: EquipmentId) => {
    setSelected(id);
    if (phase === "orient" && !learning.visited.includes(id) && !busy)
      await saveProgress({ visited: [...learning.visited, id] });
  };
  const control = (command: string) =>
    api<Session>(
      `/sessions/${current.current.id}/${command}`,
      json({ version: current.current.version }),
    );
  const perform = async (single: boolean) => {
    const next = await task(async () => {
      let run = current.current;
      if (run.status === "draft" || run.status === "paused") {
        run = await control(run.status === "draft" ? "start" : "resume");
        current.current = run;
      }
      if (single) {
        run = await control("advance");
        current.current = run;
        if (run.status === "running") run = await control("pause");
      }
      return run;
    });
    if (next && !single) setAuto(true);
  };
  useEffect(() => {
    if (!auto || busy || session.status !== "running") return;
    const timer = window.setTimeout(
      () =>
        task(async () => {
          const next = await api<Session>(
            `/sessions/${current.current.id}/advance`,
            json({ version: current.current.version }),
          );
          if (next.status !== "running" && mounted.current) setAuto(false);
          return next;
        }),
      1200,
    );
    return () => window.clearTimeout(timer);
  }, [auto, busy, session.version, session.status, task]);
  useEffect(() => {
    if (phase === "run" && session.cursor < 4)
      setSelected(
        stepExplanation(
          session.cursor,
          volume,
          session.experiment.source_volume,
        ).object as EquipmentId,
      );
  }, [phase, session.cursor, volume, session.experiment.source_volume]);
  const checkPrediction = async () => {
    if (
      Object.values(prediction).some(
        (v) => !v.trim() || !Number.isFinite(Number(v)) || Number(v) < 0,
      )
    ) {
      setPredictionMessage("请填写三个非负液量，再检查你的预测。");
      return;
    }
    const saved = await saveProgress({
      prediction: {
        source: Number(prediction.source),
        tip: Number(prediction.tip),
        target: Number(prediction.target),
      },
    });
    if (saved) {
      setPredictionDirty(false);
      setPredictionMessage(
        saved.readiness?.checks.find((check) => check.id === "prediction")
          ?.passed
          ? "预测正确。吸液先把液体装进吸头，目标孔此时仍为空。"
          : "再想一想：吸液把液体从源容器送进吸头；还没有执行排液。检查三个位置的液量。",
      );
    }
  };
  const restart = async (nextVolume: number) => {
    if (!window.confirm("保存本次尝试记录，并从初始状态重新开始？")) return;
    setAuto(false);
    const next = await task(async () => {
      const reset = await control("reset");
      current.current = reset;
      return api<Session>(
        `/sessions/${reset.id}`,
        json(
          {
            version: reset.version,
            experiment: {
              ...firstTransfer(nextVolume),
              layout: reset.experiment.layout,
            },
          },
          "PUT",
        ),
      );
    });
    if (next) {
      setPrediction({ source: "", tip: "", target: "" });
      setPredictionDirty(false);
      setPredictionMessage("");
    }
  };
  return (
    <div className={s.workspace}>
      <div className={s.breadcrumb}>
        <button onClick={onBack}>
          <ArrowLeft size={15} /> 返回课程
        </button>
        <span>FLEX / 第一课</span>
        <span className={s.source}>课程模型 · 非远程仿真</span>
      </div>
      <header className={s.heading}>
        <div>
          <span className={s.eyebrow}>从手动移液，到自动化实验</span>
          <h1>
            让 {volume} µL 液体，<em>到达正确的地方。</em>
          </h1>
          <p>
            认识设备，预测变化，再观察每个动作。所有练习都保留在你的实验记录中。
          </p>
        </div>
        <div className={s.progressRing}>
          <strong>
            {derivedDone.filter(Boolean).length}
            <small>/ 5</small>
          </strong>
          <span>学习环节</span>
        </div>
      </header>
      <div className={s.learningGrid}>
        <nav className={s.phaseNav} aria-label="课程步骤">
          <span className={s.eyebrow}>YOUR LEARNING PATH</span>
          {PHASES.map((p, i) => (
            <button
              key={p.id}
              aria-current={phase === p.id ? "step" : undefined}
              className={phase === p.id ? s.currentPhase : ""}
              onClick={() => changePhase(p.id)}
              disabled={busy || session.status === "running"}
            >
              <span className={s.phaseNumber}>
                {derivedDone[i] ? (
                  <Check size={15} />
                ) : (
                  String(i + 1).padStart(2, "0")
                )}
              </span>
              <span>
                <strong>{p.title}</strong>
                <small>{p.detail}</small>
              </span>
            </button>
          ))}
          <div className={s.pathNote}>
            <BookOpen size={19} />
            <p>
              你已经会手动移液。
              <br />
              现在，把你的判断
              <br />
              一步一步告诉机器。
            </p>
          </div>
          <a
            href="https://docs.opentrons.com/flex/"
            target="_blank"
            rel="noreferrer"
          >
            Opentrons 官方手册 ↗
          </a>
        </nav>
        <section className={s.stage} aria-label="设备与实验区域">
          <div className={s.viewTabs}>
            <button
              aria-pressed={view === "diagram"}
              onClick={() => setView("diagram")}
            >
              设备导览 <span>教学示意</span>
            </button>
            <button
              aria-pressed={view === "remote"}
              onClick={() => setView("remote")}
            >
              <Monitor size={15} /> 远程 3D <WifiOff size={13} />
            </button>
          </div>
          {view === "remote" ? (
            <RemoteView />
          ) : (
            <>
              <FlexDiagram
                session={session}
                selected={selected}
                onSelect={select}
              />
              <div className={s.objectButtons}>
                {(Object.keys(EQUIPMENT) as EquipmentId[]).map((id) => (
                  <button
                    key={id}
                    disabled={busy}
                    aria-pressed={selected === id}
                    onClick={() => select(id)}
                  >
                    {learning.visited.includes(id) ? (
                      <Check size={13} />
                    ) : (
                      <span className={s.objectDot} />
                    )}{" "}
                    {EQUIPMENT[id].name}
                  </button>
                ))}
              </div>
            </>
          )}
          <div className={s.selection}>
            <span>当前对象</span>
            <strong>{evidence.name}</strong>
            <span>
              {selected === "pipette"
                ? "机身移液器"
                : `${session.experiment.layout[selected]} 槽位${selected === "plate" ? " → 目标孔板 → A1 孔" : ""}`}
            </span>
          </div>
          {phase === "prepare" && (
            <div className={s.deckEditor}>
              <h3>把耗材放在正确的位置</h3>
              <p>
                选择一个槽位会交换其中的耗材。D3
                保留给固定废弃槽。当前布台用于位置练习，不模拟可达性。
              </p>
              <div>
                {(["stock", "plate", "tips"] as const).map((id) => (
                  <label key={id}>
                    {EQUIPMENT[id].name}
                    <select
                      aria-label={`${EQUIPMENT[id].name}槽位`}
                      disabled={busy || session.status !== "draft"}
                      value={session.experiment.layout[id]}
                      onChange={(e) => {
                        const slot = e.target.value;
                        const layout = { ...session.experiment.layout };
                        const occupant = Object.keys(layout).find(
                          (key) => layout[key] === slot,
                        );
                        if (occupant) layout[occupant] = layout[id];
                        layout[id] = slot;
                        task(() =>
                          api<Session>(
                            `/sessions/${session.id}`,
                            json(
                              {
                                version: session.version,
                                experiment: { ...session.experiment, layout },
                              },
                              "PUT",
                            ),
                          ),
                        );
                      }}
                    >
                      {[..."ABCD"]
                        .flatMap((row) =>
                          [1, 2, 3].map((col) => `${row}${col}`),
                        )
                        .filter((slot) => slot !== "D3")
                        .map((slot) => (
                          <option key={slot}>{slot}</option>
                        ))}
                    </select>
                  </label>
                ))}
              </div>
            </div>
          )}
          <div className={s.stateHeading}>
            <strong>液量观察</strong>
            <span>来源：课程模型推算</span>
          </div>
          <div className={s.liquidStates}>
            {[
              {
                name: "源容器",
                value: session.state.wells.stock.volume,
                detail: `${session.experiment.layout.stock} 槽位`,
              },
              {
                name: "吸头内",
                value: session.state.pipette.volume,
                detail: session.state.pipette.tip ? "已安装吸头" : "未安装吸头",
              },
              {
                name: "目标 A1 孔",
                value: session.state.wells.A1.volume,
                detail: `${session.experiment.layout.plate} 槽位 → 孔板`,
              },
            ].map((item) => (
              <div key={item.name}>
                <span>{item.name}</span>
                <strong>
                  {number(item.value)}
                  <small> µL</small>
                </strong>
                <small>{item.detail}</small>
              </div>
            ))}
          </div>
          <div className={s.timeline}>
            {session.experiment.actions.map((action, i) => (
              <div
                key={i}
                className={
                  i < session.cursor
                    ? s.executed
                    : i === session.cursor
                      ? s.nextAction
                      : ""
                }
              >
                <span>{i < session.cursor ? <Check size={12} /> : i + 1}</span>
                {
                  {
                    pickup: "取头",
                    aspirate: "吸液",
                    dispense: "排液",
                    drop: "弃头",
                  }[action.kind]
                }
                <small>
                  {i < session.cursor
                    ? "已完成"
                    : i === session.cursor
                      ? "下一动作"
                      : "待执行"}
                </small>
              </div>
            ))}
          </div>
        </section>
        <aside className={s.companion}>
          <span className={s.eyebrow}>
            0{phaseIndex + 1} / {PHASES[phaseIndex].title}
          </span>
          {phase === "orient" && (
            <>
              <h2>
                {evidence.name}
                <small>{evidence.english}</small>
              </h2>
              <p>{evidence.purpose}</p>
              <div className={s.comparison}>
                <span>{evidence.manual}</span>
                <ArrowRight size={15} />
                <strong>{evidence.robot}</strong>
              </div>
              <div className={s.note}>
                <CircleHelp size={16} />
                <p>{evidence.notice}</p>
              </div>
              <small>
                已探索 {new Set(learning.visited).size} / 5
                个对象。点击下方对象按钮查看说明。
              </small>
              <fieldset>
                <legend>“D2 槽位上的孔板 A1”，A1 指什么？</legend>
                {(
                  [
                    ["well", "孔板中的一个孔"],
                    ["slot", "另一个台面槽位"],
                  ] as const
                ).map(([value, label]) => (
                  <label key={value}>
                    <input
                      type="radio"
                      name="location"
                      checked={learning.location_answer === value}
                      disabled={busy}
                      onChange={() => saveProgress({ location_answer: value })}
                    />
                    {label}
                  </label>
                ))}
              </fieldset>
              {learning.location_answer === "slot" && (
                <p className={s.feedback}>
                  槽位放耗材，孔位接收液体。这句话里的 A1 属于孔板。
                </p>
              )}
              <button
                className={s.primary}
                disabled={busy || !orientDone}
                onClick={() => changePhase("prepare")}
              >
                去准备实验 <ArrowRight size={16} />
              </button>
            </>
          )}
          {phase === "prepare" && (
            <>
              <h2>
                像上实验台一样，
                <br />
                先检查准备。
              </h2>
              <p>
                这一课从 {number(session.experiment.source_volume)} µL
                源液开始，向空的 A1 孔转移 {volume} µL。
              </p>
              <div className={s.checklist}>
                {PREPARATION.map((check) => (
                  <label key={check.id}>
                    <input
                      type="checkbox"
                      disabled={busy || session.status !== "draft"}
                      checked={learning.checks.includes(check.id)}
                      onChange={() =>
                        saveProgress({
                          checks: learning.checks.includes(check.id)
                            ? learning.checks.filter((c) => c !== check.id)
                            : [...learning.checks, check.id],
                        })
                      }
                    />
                    <span>
                      <strong>{check.title}</strong>
                      <small>{check.detail}</small>
                    </span>
                  </label>
                ))}
              </div>
              <div className={s.note}>
                <CircleHelp size={16} />
                <p>
                  这份检查单是虚拟准备练习。实体 Flex 仍需真实的 Labware
                  Position Check 和现场操作培训。
                </p>
              </div>
              <button
                className={s.primary}
                disabled={busy || !orientDone || !preparationDone}
                onClick={() => changePhase("predict")}
              >
                先预测液量 <ArrowRight size={16} />
              </button>
            </>
          )}
          {phase === "predict" && (
            <>
              <h2>
                吸液结束后，
                <br />
                液体在哪里？
              </h2>
              <p>
                源容器有 {number(session.experiment.source_volume)}{" "}
                µL，吸头和目标孔均为空。执行“吸取 {volume} µL”，还没有排液。
              </p>
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  checkPrediction();
                }}
                className={s.predictionForm}
              >
                {(
                  [
                    { key: "source", label: "源容器剩余" },
                    { key: "tip", label: "吸头内液量" },
                    { key: "target", label: "目标 A1 孔液量" },
                  ] as const
                ).map((field) => (
                  <label key={field.key}>
                    {field.label}
                    <div>
                      <input
                        type="number"
                        min="0"
                        max={field.key === "tip" ? 300 : 1500}
                        step="any"
                        required
                        value={prediction[field.key]}
                        disabled={busy || session.status !== "draft"}
                        onChange={(e) => {
                          setPrediction({
                            ...prediction,
                            [field.key]: e.target.value,
                          });
                          setPredictionDirty(true);
                          setPredictionMessage("");
                        }}
                      />
                      <span>µL</span>
                    </div>
                  </label>
                ))}
                <button
                  className={s.secondary}
                  disabled={busy || session.status !== "draft"}
                >
                  检查我的预测
                </button>
              </form>
              <p role="status" className={s.feedback}>
                {predictionMessage ||
                  (predictionDone
                    ? "已保存正确预测。运行时将它与模型结果对照。"
                    : "提示：三个位置的总液量应该保持不变。")}
              </p>
              <button
                className={s.primary}
                disabled={busy || !session.readiness?.ready || predictionDirty}
                onClick={() => changePhase("run")}
              >
                进入操作练习 <ArrowRight size={16} />
              </button>
            </>
          )}
          {phase === "run" && (
            <>
              <h2>
                {session.status === "completed"
                  ? "转移完成。现在解释它。"
                  : explanation.title}
              </h2>
              <span className={s.english}>
                {session.status === "completed"
                  ? "Practice complete"
                  : explanation.english}
              </span>
              {session.status !== "completed" ? (
                <>
                  <h3>为什么这样做</h3>
                  <p>{explanation.why}</p>
                  <h3>操作前需要</h3>
                  <p>{explanation.before}</p>
                  <div className={s.expected}>
                    <span>预计观察到</span>
                    <strong>{explanation.expect}</strong>
                  </div>
                </>
              ) : (
                <>
                  <p>
                    对照你的预测，检查源容器、吸头和目标孔。流程完成之后，还需要解释液体是怎样到达目标的。
                  </p>
                  <div className={s.assessment}>
                    {session.assessment?.checks.map((c) => (
                      <p key={c.label}>
                        <CheckCircle2 size={15} />
                        {c.label}
                      </p>
                    ))}
                  </div>
                </>
              )}
              {!session.readiness?.ready && (
                <div className={s.note}>
                  <CircleHelp size={16} />
                  <div>
                    <p>运行前还有准备未完成：</p>
                    {session.readiness?.checks
                      .filter((c) => !c.passed)
                      .map((c) => (
                        <p key={c.id}>{c.label}</p>
                      ))}
                  </div>
                </div>
              )}
              {session.status === "faulted" && (
                <div role="alert" className={s.note}>
                  <p>
                    {session.events.at(-1)?.message}
                    <br />
                    {session.events.at(-1)?.hint}
                  </p>
                </div>
              )}
              {session.status === "completed" ? (
                <button
                  className={s.primary}
                  disabled={busy}
                  onClick={() => changePhase("reflect")}
                >
                  解释结果并再试一次 <ArrowRight size={16} />
                </button>
              ) : session.status === "faulted" ? (
                <button
                  className={s.primary}
                  disabled={busy}
                  onClick={() => restart(volume)}
                >
                  从初始状态重试
                </button>
              ) : (
                <div className={s.runControls}>
                  <button
                    className={s.primary}
                    disabled={busy || !session.readiness?.ready || auto}
                    onClick={() => perform(true)}
                  >
                    <SkipForward size={16} />
                    {busy ? "正在执行…" : "执行下一步"}
                  </button>
                  {auto || session.status === "running" ? (
                    <button
                      className={s.secondary}
                      disabled={busy}
                      onClick={() => {
                        setAuto(false);
                        task(() => control("pause"));
                      }}
                    >
                      <Pause size={15} /> 暂停练习
                    </button>
                  ) : (
                    <button
                      className={s.secondary}
                      disabled={busy || !session.readiness?.ready}
                      onClick={() => perform(false)}
                    >
                      <Play size={15} /> 连续运行
                    </button>
                  )}
                </div>
              )}
              <small>
                每次单步在动作结束后暂停。教学模型在离开页面后不继续自动执行。
              </small>
              <details>
                <summary>查看本次动作记录 · {session.events.length}</summary>
                {session.events.length ? (
                  session.events.map((event, i) => (
                    <p key={i}>
                      {event.step}. {event.message}
                    </p>
                  ))
                ) : (
                  <p>还没有执行动作。</p>
                )}
              </details>
            </>
          )}
          {phase === "reflect" && (
            <>
              <h2>
                {completed ? "你已经解释了第一次转移。" : "做完之后，想明白。"}
              </h2>
              <p>吸液结束、排液开始之前，液体从哪里到了哪里？</p>
              <fieldset>
                <legend>选择与动作相符的解释</legend>
                {(
                  [
                    ["source_to_tip", "从源容器进入吸头，目标孔仍为空"],
                    ["source_to_target", "从源容器直接到达目标孔"],
                    ["target_to_tip", "从目标孔回到吸头"],
                  ] as const
                ).map(([value, label]) => (
                  <label key={value}>
                    <input
                      type="radio"
                      name="reflection"
                      disabled={busy || session.status !== "completed"}
                      checked={learning.reflection === value}
                      onChange={() => saveProgress({ reflection: value })}
                    />
                    {label}
                  </label>
                ))}
              </fieldset>
              {session.status !== "completed" ? (
                <p className={s.feedback}>先完成一次转移，再对照结果作答。</p>
              ) : learning.reflection &&
                learning.reflection !== "source_to_tip" ? (
                <p className={s.feedback}>
                  吸液时目标孔还没有收到液体。排液才把吸头里的液体送入目标。
                </p>
              ) : completed ? (
                <div className={s.success}>
                  <CheckCircle2 size={22} />
                  <strong>操作与理解均已完成</strong>
                  <p>这次记录来自教学模型，不代表实体机器操作认证。</p>
                </div>
              ) : null}
              <h3>换一个条件，再试一次</h3>
              <p>
                把体积改为 {volume === 100 ? 50 : 100}{" "}
                µL，重新检查并预测。你可以不依赖上一轮答案完成吗？
              </p>
              <button
                className={s.primary}
                disabled={busy || session.status !== "completed"}
                onClick={() => restart(volume === 100 ? 50 : 100)}
              >
                <RotateCcw size={16} /> 挑战 {volume === 100 ? 50 : 100} µL 转移
              </button>
              <small>
                本实验保留最近 10 次尝试摘要。已有 {session.attempts.length}{" "}
                次历史尝试。
              </small>
              <div className={s.note}>
                <FlaskConical size={17} />
                <p>
                  下一课：连续稀释。它还需要稀释液、混匀和多个目标孔；当前稀释练习采用理想混合假设。
                </p>
              </div>
            </>
          )}
        </aside>
      </div>
      <div className={s.lessonFooter}>
        <span>
          <CheckCircle2 size={14} />{" "}
          {busy
            ? "正在保存或执行…"
            : predictionDirty
              ? "预测尚未保存"
              : "学习进度已保存"}
        </span>
        <span>课程 v1 · 自由探索设备，按检查点开始运行</span>
      </div>
    </div>
  );
}
