import s from "./App.module.css";

export const LABWARE: Record<string, { name: string; detail: string }> = {
  stock: { name: "Stock solution", detail: "1,500 µL vial" },
  plate: { name: "Destination wells", detail: "A1 · A2 · A3" },
  tips: { name: "Tip rack", detail: "96 × 300 µL" },
  waste: { name: "Waste chute", detail: "Used tips" },
};
export const SLOTS = "ABCD"
  .split("")
  .flatMap((row) => [1, 2, 3].map((col) => `${row}${col}`));
export const LABELS = {
  pickup: "Pick up tip",
  aspirate: "Aspirate",
  dispense: "Dispense",
  drop: "Discard tip",
};
export const format = (n: number) => Number(n.toFixed(2)).toLocaleString();

export function LabwareDrawing({ kind }: { kind: string }) {
  if (kind === "tips")
    return (
      <div className={s.tipRack}>
        {Array.from({ length: 24 }, (_, i) => (
          <i key={i} />
        ))}
      </div>
    );
  if (kind === "plate")
    return (
      <div className={s.wellPlate}>
        {Array.from({ length: 6 }, (_, i) => (
          <i key={i} />
        ))}
      </div>
    );
  if (kind === "stock")
    return (
      <div className={s.vial}>
        <span />
        <i />
      </div>
    );
  return (
    <div className={s.chute}>
      <span />
    </div>
  );
}

export function Deck({
  layout,
  selected,
  onPlace,
  locked = false,
  large = false,
}: {
  layout: Record<string, string>;
  selected?: string | null;
  onPlace?: (slot: string, asset?: string) => void;
  locked?: boolean;
  large?: boolean;
}) {
  return (
    <div className={`${s.deck} ${large ? s.largeDeck : ""}`}>
      <div className={s.deckRail}>
        <span>FLEX</span>
        <i />
        <span>DECK / TOP VIEW</span>
      </div>
      <div className={s.deckSlots}>
        {SLOTS.map((slot) => {
          const asset = Object.keys(layout).find((key) => layout[key] === slot);
          return (
            <button
              key={slot}
              className={`${s.slot} ${asset ? s.occupied : ""} ${selected && asset === selected ? s.selectedSlot : ""}`}
              aria-label={`${slot}${asset ? `: ${LABWARE[asset].name}` : ": empty"}${selected ? " — place selected labware" : ""}`}
              disabled={locked || !onPlace}
              onClick={() => onPlace?.(slot)}
              onDragOver={(e) => {
                if (!locked) e.preventDefault();
              }}
              onDrop={(e) => {
                e.preventDefault();
                if (!locked)
                  onPlace?.(slot, e.dataTransfer.getData("text/plain"));
              }}
            >
              <span className={s.slotLabel}>{slot}</span>
              {asset && (
                <>
                  <LabwareDrawing kind={asset} />
                  <span className={s.assetLabel}>{LABWARE[asset].name}</span>
                </>
              )}
            </button>
          );
        })}
      </div>
      <div className={s.deckFoot}>
        <span>OPENTRONS FLEX</span>
        <span>SCHEMATIC PREVIEW</span>
      </div>
    </div>
  );
}
