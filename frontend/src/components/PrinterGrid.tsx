import type { Marker, Printer } from "../api";
import { ago, PRINTER_TONE } from "../lib/format";
import { IconAlert, IconCheck, IconColor, IconDuplex, IconPin, IconQuestion, IconStaple } from "./Icons";
import { PrinterArt } from "./PrinterArt";
import { Chip } from "./ui";

/** States in which sending a job is pointless or will fail. */
export function printerBlocked(p: Printer): string | null {
  if (!p.enabled) return "Disabled by an administrator";
  if (p.status.state === "offline") return "Offline — jobs can't be delivered right now";
  if (p.status.state === "stopped") return "Paused — the print queue isn't accepting jobs";
  if (p.capabilities_error) return "Its options couldn't be read, so printing to it is blocked";
  return null;
}

function Supplies({ markers }: { markers: Marker[] }) {
  return (
    <div className="supplies" aria-label="Supply levels reported by the printer">
      {markers.map((m) => {
        const low = m.level !== null && m.low !== null && m.level <= m.low;
        return (
          <div className="supply" key={m.name} title={`${m.name}: ${m.level !== null ? `${m.level}%` : m.note ?? "not reported"}`}>
            <div className="supply-bar">
              <span style={{ height: `${m.level ?? 0}%`, background: m.color ?? "var(--text-3)" }} />
            </div>
            <small style={low ? { color: "var(--bad)" } : undefined}>{m.level !== null ? `${m.level}%` : "?"}</small>
          </div>
        );
      })}
    </div>
  );
}

export function PrinterCard({ printer, selected, onSelect }: { printer: Printer; selected: boolean; onSelect: () => void }) {
  const blocked = printerBlocked(printer);
  const st = printer.status;
  const tone = PRINTER_TONE[st.state];
  const caps = printer.capability_summary;
  const warnings = st.reasons.filter((r) => r.severity !== "report" || st.state === "offline");
  return (
    <button
      type="button"
      className="printer-card"
      aria-pressed={selected}
      aria-disabled={!!blocked}
      aria-describedby={`ps-${printer.id}`}
      onClick={() => !blocked && onSelect()}
    >
      <div className="printer-art">
        <span className="status-pin">
          <Chip tone={tone}>
            {st.state === "unknown" ? <IconQuestion size={12} /> : null}
            {st.label}
          </Chip>
        </span>
        {selected && (
          <span className="selected-tick" aria-hidden="true">
            <IconCheck size={18} />
          </span>
        )}
        <PrinterArt kind={printer.image} />
      </div>
      <div className="printer-body">
        <span className="printer-name">{printer.display_name}</span>
        {printer.location && (
          <span className="printer-loc">
            <IconPin size={15} /> {printer.location}
          </span>
        )}
        <span className="printer-model">{printer.make_model || "Model not identified yet"}</span>

        {caps ? (
          <div className="cap-row" aria-label="Capabilities">
            <span className="cap">
              <IconColor /> {caps.color ? "Color" : "B&W only"}
            </span>
            <span className="cap">
              <IconDuplex /> {caps.duplex ? "Double-sided" : "Single-sided"}
            </span>
            {caps.finishing.length > 0 && (
              <span className="cap">
                <IconStaple /> {caps.finishing.length === 1 ? caps.finishing[0] : "Finishing"}
              </span>
            )}
            {caps.media.slice(0, 2).map((m) => (
              <span className="cap" key={m}>
                {m}
              </span>
            ))}
          </div>
        ) : (
          <span className="subtle">{printer.capabilities_error ?? "Capabilities not read yet"}</span>
        )}

        <div id={`ps-${printer.id}`} className="stack" style={{ gap: 4 }}>
          {blocked && (
            <span className="printer-warn bad">
              <IconAlert size={14} /> {blocked}
            </span>
          )}
          {warnings.slice(0, 2).map((r) => (
            <span key={r.keyword} className={`printer-warn ${r.severity === "error" ? "bad" : ""}`}>
              <IconAlert size={14} /> {r.explanation}
            </span>
          ))}
          {st.message && !warnings.length && st.state !== "ready" && <span className="subtle">{st.message}</span>}
          {st.state === "unknown" && (
            <span className="subtle">{st.error ?? "The printer hasn't reported its status."} Status unknown is not the same as ready.</span>
          )}
        </div>

        {st.markers && st.markers.length > 0 && <Supplies markers={st.markers} />}
        <span className="subtle" style={{ fontSize: "0.72rem", marginTop: "auto" }}>
          {printer.simulated ? "Simulated printer · " : ""}
          {st.checked_at ? `Status checked ${ago(st.checked_at)}` : "Status not checked yet"}
        </span>
      </div>
    </button>
  );
}

export default function PrinterGrid({ printers, selectedId, onSelect }: { printers: Printer[]; selectedId: string | null; onSelect: (id: string) => void }) {
  if (!printers.length) {
    return (
      <div className="card empty">
        <h3>No printers connected yet</h3>
        <p>An administrator needs to add a printer in CUPS and connect it in Admin → Printers.</p>
      </div>
    );
  }
  return (
    <div className="printer-grid" role="group" aria-label="Choose a printer">
      {printers.map((p) => (
        <PrinterCard key={p.id} printer={p} selected={p.id === selectedId} onSelect={() => onSelect(p.id)} />
      ))}
    </div>
  );
}
