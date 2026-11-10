import { ArrowLeft, Copy, Trash2, Users } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, json } from "./api";
import s from "./StudyGroups.module.css";
import type { Experiment, Session } from "./types";

type Member = { id?: string; name: string; role: "facilitator" | "member" };
type Share = {
  id: string;
  version: number;
  member_id: string;
  author: string;
  shared_at: string;
  experiment: Experiment;
  evidence: "synthetic";
  status: Session["status"];
  passed: boolean | null;
  comments: { author: string; text: string; at: string }[];
};
type Group = {
  id: string;
  name: string;
  version: number;
  code: string | null;
  you: Member & { id: string };
  members: Member[];
  shares: Share[];
};
type Listing = {
  groups: { id: string; name: string; members: number; shares: number }[];
  can_create: boolean;
};

const statusText: Record<Session["status"], string> = {
  draft: "Not run yet",
  running: "Running",
  paused: "Paused",
  faulted: "Stopped with a fault",
  completed: "Completed",
};

function outcome(share: Share) {
  if (share.status !== "completed") return statusText[share.status];
  return share.passed ? "Teaching run passed" : "Teaching run needs work";
}

function setRoute(groupId: string | null) {
  window.history.replaceState(
    {},
    "",
    groupId ? `/#/groups/${groupId}` : "/#/groups",
  );
}

export default function StudyGroups({
  initialGroupId,
  sessions,
  onCopied,
  onError,
}: {
  initialGroupId?: string;
  sessions: Session[];
  onCopied: (session: Session) => void;
  onError: (message: string) => void;
}) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [group, setGroup] = useState<Group | null>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(
    async <T,>(work: () => Promise<T>) => {
      setBusy(true);
      try {
        return await work();
      } catch (e) {
        onError((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
    [onError],
  );

  const openGroup = useCallback(
    (id: string) =>
      run(async () => {
        setGroup(await api<Group>(`/groups/${id}`));
        setRoute(id);
      }),
    [run],
  );

  useEffect(() => {
    if (initialGroupId) void openGroup(initialGroupId);
    else void run(async () => setListing(await api<Listing>("/groups")));
  }, [initialGroupId, openGroup, run]);

  if (group)
    return (
      <GroupPage
        group={group}
        sessions={sessions}
        busy={busy}
        run={run}
        onChange={setGroup}
        onCopied={onCopied}
        onBack={() => {
          setGroup(null);
          setRoute(null);
          void run(async () => setListing(await api<Listing>("/groups")));
        }}
      />
    );

  const submit =
    (path: string, field: "name" | "code") =>
    (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const value = new FormData(event.currentTarget).get(field);
      void run(async () => {
        const next = await api<Group>(path, json({ [field]: value }));
        setGroup(next);
        setRoute(next.id);
      });
    };

  return (
    <div className={s.page}>
      <h1>Study groups</h1>
      <div className={s.entry}>
        <form onSubmit={submit("/groups/join", "code")}>
          <h2>Join a group</h2>
          <label htmlFor="group-code">Join code</label>
          <div className={s.inline}>
            <input
              id="group-code"
              name="code"
              required
              minLength={8}
              maxLength={8}
              autoComplete="off"
              spellCheck={false}
            />
            <button className={s.primary} disabled={busy}>
              Join
            </button>
          </div>
        </form>
        <form onSubmit={submit("/groups", "name")}>
          <h2>Start a group</h2>
          <label htmlFor="group-name">Group name</label>
          <div className={s.inline}>
            <input
              id="group-name"
              name="name"
              required
              maxLength={60}
              disabled={listing?.can_create === false}
            />
            <button
              className={s.secondary}
              disabled={busy || listing?.can_create === false}
            >
              Create
            </button>
          </div>
          {listing?.can_create === false && (
            <p className={s.reason}>
              Instructors create groups. Ask yours for a join code.
            </p>
          )}
        </form>
      </div>
      {listing && listing.groups.length > 0 && (
        <section aria-labelledby="my-groups">
          <h2 id="my-groups">Your groups</h2>
          <ul className={s.groups}>
            {listing.groups.map((item) => (
              <li key={item.id}>
                <button onClick={() => void openGroup(item.id)}>
                  <strong>{item.name}</strong>
                  <span>
                    {item.members} {item.members === 1 ? "member" : "members"} ·{" "}
                    {item.shares} shared
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function GroupPage({
  group,
  sessions,
  busy,
  run,
  onChange,
  onCopied,
  onBack,
}: {
  group: Group;
  sessions: Session[];
  busy: boolean;
  run: <T>(work: () => Promise<T>) => Promise<T | undefined>;
  onChange: (group: Group) => void;
  onCopied: (session: Session) => void;
  onBack: () => void;
}) {
  const [compare, setCompare] = useState<string[]>([]);
  const reload = async () => onChange(await api<Group>(`/groups/${group.id}`));
  const base = `/groups/${group.id}/shares`;
  const compared = compare
    .map((id) => group.shares.find((share) => share.id === id))
    .filter((share): share is Share => Boolean(share));

  return (
    <div className={s.page}>
      <button className={s.back} onClick={onBack}>
        <ArrowLeft size={16} /> Study groups
      </button>
      <div className={s.heading}>
        <h1>{group.name}</h1>
        {group.code && (
          <div className={s.code}>
            <span>Join code</span>
            <strong>{group.code}</strong>
            <button
              className={s.icon}
              aria-label="Copy join code"
              onClick={() => void navigator.clipboard?.writeText(group.code!)}
            >
              <Copy size={15} />
            </button>
          </div>
        )}
      </div>
      <ul className={s.members} aria-label="Members">
        {group.members.map((member, index) => (
          <li key={index}>
            <Users size={14} aria-hidden="true" /> {member.name}
            {member.role === "facilitator" && <small>facilitator</small>}
          </li>
        ))}
      </ul>

      <form
        className={s.shareForm}
        onSubmit={(event) => {
          event.preventDefault();
          const id = new FormData(event.currentTarget).get("session");
          void run(async () => {
            await api(base, json({ session_id: id }));
            await reload();
          });
        }}
      >
        <label htmlFor="share-session">Share one of your experiments</label>
        <div className={s.inline}>
          <select id="share-session" name="session" required>
            {sessions.map((session) => (
              <option key={session.id} value={session.id}>
                {session.experiment.title}
              </option>
            ))}
          </select>
          <button
            className={s.primary}
            disabled={busy || sessions.length === 0}
          >
            Share
          </button>
        </div>
        {sessions.length === 0 && (
          <p className={s.reason}>Start an experiment first.</p>
        )}
      </form>

      {compared.length === 2 && <Comparison shares={compared} />}

      <section aria-labelledby="shared-title">
        <h2 id="shared-title">Shared experiments</h2>
        {group.shares.length === 0 ? (
          <p className={s.empty}>
            Nothing shared yet. Each member builds their own version, shares it
            here, and the group compares them.
          </p>
        ) : (
          <ul className={s.shares}>
            {group.shares.map((share) => (
              <ShareCard
                key={share.id}
                share={share}
                canRemove={
                  share.member_id === group.you.id ||
                  group.you.role === "facilitator"
                }
                selected={compare.includes(share.id)}
                busy={busy}
                onSelect={(on) =>
                  setCompare((current) =>
                    on
                      ? [
                          ...current.filter((id) => id !== share.id),
                          share.id,
                        ].slice(-2)
                      : current.filter((id) => id !== share.id),
                  )
                }
                onCopy={() =>
                  run(async () =>
                    onCopied(
                      await api<Session>(`${base}/${share.id}/copy`, {
                        method: "POST",
                      }),
                    ),
                  )
                }
                onRemove={() =>
                  run(async () => {
                    await api(
                      `${base}/${share.id}/remove`,
                      json({ version: share.version }),
                    );
                    setCompare((current) =>
                      current.filter((id) => id !== share.id),
                    );
                    await reload();
                  })
                }
                onComment={(text) =>
                  run(async () => {
                    await api(
                      `${base}/${share.id}/comments`,
                      json({ version: share.version, text }),
                    );
                    await reload();
                    return true;
                  })
                }
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function ShareCard({
  share,
  canRemove,
  selected,
  busy,
  onSelect,
  onCopy,
  onRemove,
  onComment,
}: {
  share: Share;
  canRemove: boolean;
  selected: boolean;
  busy: boolean;
  onSelect: (on: boolean) => void;
  onCopy: () => void;
  onRemove: () => void;
  onComment: (text: string) => Promise<boolean | undefined>;
}) {
  const [draft, setDraft] = useState("");
  const { experiment } = share;
  const title = `${experiment.title} by ${share.author}`;
  return (
    <li className={selected ? s.selected : ""}>
      <div className={s.shareTop}>
        <div>
          <h3>{experiment.title}</h3>
          <p>
            {share.author} · {instrument(experiment)}·{" "}
            {experiment.actions.length} steps
          </p>
        </div>
        <label className={s.check}>
          <input
            type="checkbox"
            checked={selected}
            onChange={(event) => onSelect(event.target.checked)}
            aria-label={`Compare ${title}`}
          />
          Compare
        </label>
      </div>
      <p className={s.outcome}>{outcome(share)}</p>
      <div className={s.actions}>
        <button className={s.secondary} disabled={busy} onClick={onCopy}>
          Make my own copy
        </button>
        {canRemove && (
          <button
            className={s.icon}
            disabled={busy}
            aria-label={`Remove ${title}`}
            onClick={onRemove}
          >
            <Trash2 size={15} />
          </button>
        )}
      </div>
      <details className={s.discussion}>
        <summary>
          Discussion{share.comments.length > 0 && ` (${share.comments.length})`}
        </summary>
        <ul>
          {share.comments.map((comment, index) => (
            <li key={index}>
              <strong>{comment.author}</strong> {comment.text}
            </li>
          ))}
        </ul>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            void onComment(draft).then((ok) => ok && setDraft(""));
          }}
        >
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            maxLength={500}
            required
            aria-label={`Comment on ${title}`}
          />
          <button className={s.secondary} disabled={busy}>
            Post
          </button>
        </form>
      </details>
    </li>
  );
}

function step(action: Experiment["actions"][number] | undefined) {
  if (!action) return "—";
  if (action.kind === "pickup") return "Pick up tip";
  if (action.kind === "drop") return "Drop tip";
  const verb = action.kind === "aspirate" ? "Aspirate" : "Dispense";
  return `${verb} ${action.volume} µL ${action.kind === "aspirate" ? "from" : "into"} ${action.well}`;
}

const instrument = (experiment: Experiment) =>
  experiment.instrument === "ot2" ? "OT-2" : "Flex";

function Comparison({ shares }: { shares: Share[] }) {
  const [a, b] = shares.map((share) => share.experiment);
  const labware = [
    ...new Set([...Object.keys(a.layout), ...Object.keys(b.layout)]),
  ].sort();
  const rows: [string, string, string][] = [
    ["Instrument", instrument(a), instrument(b)],
    [
      "Transfer volume",
      `${a.transfer_volume ?? 100} µL`,
      `${b.transfer_volume ?? 100} µL`,
    ],
    ["Source volume", `${a.source_volume} µL`, `${b.source_volume} µL`],
    ["Diluent volume", `${a.diluent_volume} µL`, `${b.diluent_volume} µL`],
    ...labware.map((slot): [string, string, string] => [
      `${slot[0].toUpperCase()}${slot.slice(1)} slot`,
      a.layout[slot] ?? "—",
      b.layout[slot] ?? "—",
    ]),
    ...Array.from(
      { length: Math.max(a.actions.length, b.actions.length) },
      (_, i): [string, string, string] => [
        `Step ${i + 1}`,
        step(a.actions[i]),
        step(b.actions[i]),
      ],
    ),
  ];
  const differences = rows.filter(([, x, y]) => x !== y).length;
  const [everything, setEverything] = useState(false);
  const shown =
    everything || differences === 0 ? rows : rows.filter(([, x, y]) => x !== y);
  return (
    <section aria-labelledby="compare-title" className={s.compare}>
      <h2 id="compare-title">
        {differences === 0
          ? "These two are identical"
          : `${differences} ${differences === 1 ? "difference" : "differences"} to discuss`}
      </h2>
      <div
        className={s.tableScroll}
        role="region"
        aria-labelledby="compare-title"
        tabIndex={0}
      >
        <table>
          <thead>
            <tr>
              <th scope="col">
                <span className={s.srOnly}>Setting</span>
              </th>
              {shares.map((share) => (
                <th scope="col" key={share.id}>
                  {share.author}
                  <small>{share.experiment.title}</small>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map(([label, x, y]) => (
              <tr key={label} className={x !== y ? s.differs : ""}>
                <th scope="row">
                  {label}
                  {x !== y && <span className={s.srOnly}> (differs)</span>}
                </th>
                <td>{x}</td>
                <td>{y}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {differences > 0 && (
        <button
          className={s.toggle}
          aria-expanded={everything}
          onClick={() => setEverything(!everything)}
        >
          {everything
            ? "Show only differences"
            : `Show all ${rows.length} settings and steps`}
        </button>
      )}
    </section>
  );
}
