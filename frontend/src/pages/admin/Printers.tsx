import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { del, get, patch, post, type Capabilities, type Choice, type Job, type Printer, type Settings } from "../../api";
import { IconAlert, IconInfo, IconRefresh } from "../../components/Icons";
import { PrinterArt } from "../../components/PrinterArt";
import { Chip, Dialog, Spinner, useToast } from "../../components/ui";
import { ago, PRINTER_TONE } from "../../lib/format";

interface Queue {
  queue_name: string;
  make_model: string;
  location: string;
  info: string;
  connection: string;
  registered: boolean;
}

const IMAGES = ["laser", "mfp", "inkjet", "label", "plotter", "unknown"];

export default function AdminPrinters() {
  const toast = useToast();
  const navigate = useNavigate();
  const [data, setData] = useState<{ simulated: boolean; printers: Printer[]; queues: Queue[]; discover_error: string | null } | null>(null);
  const [editing, setEditing] = useState<Printer | null>(null);
  const [connecting, setConnecting] = useState<Queue | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [testFor, setTestFor] = useState<Printer | null>(null);

  const load = useCallback(() => get("/api/admin/printers").then(setData).catch((e) => toast({ title: "Couldn't load printers", body: e.message, tone: "bad" })), [toast]);
  useEffect(() => {
    load();
  }, [load]);

  const refresh = async (p: Printer) => {
    setBusy(p.id);
    try {
      const r = await post<Printer & { refresh_error: string | null }>(`/api/admin/printers/${p.id}/refresh`);
      toast(r.refresh_error ? { title: "Capabilities unavailable", body: r.refresh_error, tone: "warn" } : { title: `${p.display_name}: ${r.status.label}` });
      load();
    } finally {
      setBusy(null);
    }
  };

  const testPage = async (p: Printer) => {
    setTestFor(null);
    setBusy(p.id);
    try {
      const r = await post<{ job: Job }>(`/api/admin/printers/${p.id}/test-page`);
      navigate(`/jobs/${r.job.id}`);
    } catch (e: any) {
      toast({ title: "Test page not sent", body: e.message, tone: "bad" });
    } finally {
      setBusy(null);
    }
  };

  const toggle = async (p: Printer) => {
    await patch(`/api/admin/printers/${p.id}`, { enabled: !p.enabled });
    toast({ title: `${p.display_name} ${p.enabled ? "disabled" : "enabled"}` });
    load();
  };

  if (!data) return <div className="skeleton" style={{ height: 240 }} />;
  const unregistered = data.queues.filter((q) => !q.registered);

  return (
    <div className="stack-lg">
      {data.simulated && (
        <div className="callout callout-sim">
          <IconInfo />
          <span>Demo mode: these printers are simulated and fixed. Switch the service to production mode to connect real CUPS queues.</span>
        </div>
      )}

      <section className="stack">
        <h3>Connected printers</h3>
        <div className="table-wrap card">
          <table className="table">
            <thead>
              <tr>
                <th>Printer</th>
                <th>Status</th>
                <th>Connection</th>
                <th>Capabilities</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {data.printers.map((p) => (
                <tr key={p.id}>
                  <td>
                    <div className="row" style={{ flexWrap: "nowrap" }}>
                      <div style={{ width: 54, flex: "none" }}>
                        <PrinterArt kind={p.image} />
                      </div>
                      <div>
                        <b>{p.display_name}</b>
                        <div className="subtle">{p.location || "No location"} · {p.make_model || "model unknown"}</div>
                        <div className="subtle mono">{p.queue_name}</div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <Chip tone={PRINTER_TONE[p.status.state]}>{p.status.label}</Chip>
                    <div className="subtle">checked {ago(p.status.checked_at)}</div>
                    {p.status.reachability && <div className="subtle">{p.status.reachability.detail}</div>}
                    {p.status.error && <div className="subtle">{p.status.error}</div>}
                  </td>
                  <td className="subtle">{p.connection}</td>
                  <td>
                    {p.capability_summary ? (
                      <span className="subtle">
                        {p.capability_summary.color ? "Color" : "B&W"} · {p.capability_summary.duplex ? "Duplex" : "Simplex"} · {p.capability_summary.media.length} sizes
                        {p.capability_summary.finishing.length ? ` · ${p.capability_summary.finishing.join(", ")}` : ""}
                      </span>
                    ) : (
                      <span className="printer-warn">
                        <IconAlert size={14} /> {p.capabilities_error ?? "Not read yet"}
                      </span>
                    )}
                  </td>
                  <td>
                    <div className="row" style={{ justifyContent: "flex-end", flexWrap: "nowrap" }}>
                      <button className="btn btn-sm" onClick={() => refresh(p)} disabled={busy === p.id} aria-label={`Check ${p.display_name} now`}>
                        {busy === p.id ? <Spinner /> : <IconRefresh size={14} />}
                      </button>
                      <button className="btn btn-sm" onClick={() => setTestFor(p)} disabled={!p.enabled || busy === p.id}>
                        Test page
                      </button>
                      <button className="btn btn-sm" onClick={() => setEditing(p)}>
                        Edit
                      </button>
                      <button className="btn btn-sm" onClick={() => toggle(p)}>
                        {p.enabled ? "Disable" : "Enable"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {data.printers.length === 0 && (
                <tr>
                  <td colSpan={5} className="subtle">
                    No printers connected yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {!data.simulated && (
        <section className="two-col">
          <div className="card card-pad stack">
            <h3>CUPS queues not yet connected</h3>
            {data.discover_error && (
              <div className="callout callout-bad">
                <IconAlert />
                <span>{data.discover_error}</span>
              </div>
            )}
            {unregistered.length === 0 && !data.discover_error && <p className="subtle">Every CUPS queue on this station is connected.</p>}
            {unregistered.map((q) => (
              <div key={q.queue_name} className="row-between" style={{ borderTop: "1px solid var(--line)", paddingTop: 12 }}>
                <div>
                  <b>{q.info || q.queue_name}</b>
                  <div className="subtle">{q.make_model} · {q.connection}</div>
                </div>
                <button className="btn btn-sm btn-primary" onClick={() => setConnecting(q)}>
                  Connect
                </button>
              </div>
            ))}
          </div>
          <div className="card card-pad stack">
            <h3>Adding a new printer</h3>
            <ol className="onboard-steps">
              <li>Record the exact model, serial and connection (network IP, USB) in docs/PRINTERS.md.</li>
              <li>Check Linux support (IPP Everywhere / driverless first) and that the station can reach it.</li>
              <li>Add it in CUPS on the station (see docs/OPERATIONS.md › Adding a printer).</li>
              <li>Connect the queue here, then press refresh and review the capabilities it reports.</li>
              <li>Print a test page and check the physical output.</li>
              <li>Run the physical checklist in docs/TESTING.md: copies, color, duplex, orientation, scaling, paper.</li>
            </ol>
            <p className="subtle">Printer firmware updates are manufacturer-specific and are done from the printer's own tools, not from the hub.</p>
          </div>
        </section>
      )}

      {editing && <EditPrinter printer={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} simulated={data.simulated} />}
      {connecting && <ConnectQueue queue={connecting} onClose={() => setConnecting(null)} onSaved={() => { setConnecting(null); load(); }} />}
      {testFor && (
        <Dialog title="Print a test page?" size="sm" onClose={() => setTestFor(null)}
          footer={<>
            <button className="btn" onClick={() => setTestFor(null)}>Cancel</button>
            <button className="btn btn-primary" onClick={() => testPage(testFor)} data-autofocus>{testFor.simulated ? "Simulate test page" : "Print test page"}</button>
          </>}>
          <p className="muted">
            {testFor.simulated
              ? "This sends a simulated job; nothing prints."
              : `This sends one page to ${testFor.display_name}. It is tracked like any job — check the printer for the physical page.`}
          </p>
        </Dialog>
      )}
    </div>
  );
}

function EditPrinter({ printer, onClose, onSaved, simulated }: { printer: Printer; onClose: () => void; onSaved: () => void; simulated: boolean }) {
  const toast = useToast();
  const [form, setForm] = useState({ display_name: printer.display_name, location: printer.location, image: printer.image, notes: printer.notes ?? "" });
  const [defaults, setDefaults] = useState<Settings>(printer.defaults ?? {});
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [capsError, setCapsError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    get<{ capabilities: Capabilities }>(`/api/printers/${printer.id}/capabilities`)
      .then((r) => setCaps(r.capabilities))
      .catch((e) => setCapsError(e.message));
  }, [printer.id]);
  const save = async () => {
    setBusy(true);
    try {
      await patch(`/api/admin/printers/${printer.id}`, { ...form, ...(caps ? { defaults } : {}) });
      toast({ title: "Printer saved" });
      onSaved();
    } catch (e: any) {
      toast({ title: "Not saved", body: e.message, tone: "bad" });
      setBusy(false);
    }
  };
  const remove = async () => {
    await del(`/api/admin/printers/${printer.id}`);
    toast({ title: "Printer disconnected", body: "Printers with job history are disabled instead of removed." });
    onSaved();
  };
  return (
    <Dialog title={`Edit ${printer.display_name}`} size="sm" onClose={onClose} busy={busy}
      footer={<>
        {!simulated && <button className="btn btn-danger" onClick={remove}>Disconnect</button>}
        <span className="grow" />
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy || !form.display_name.trim()}>{busy ? <Spinner /> : "Save"}</button>
      </>}>
      <div className="stack">
        <div className="field">
          <label htmlFor="pn">Friendly name</label>
          <input id="pn" className="input" maxLength={60} value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="pl">Location</label>
          <input id="pl" className="input" maxLength={80} value={form.location} placeholder="e.g. Studio · 2nd floor" onChange={(e) => setForm({ ...form, location: e.target.value })} />
        </div>
        <div className="field">
          <span className="field-label">Illustration</span>
          <div className="row">
            {IMAGES.map((img) => (
              <button key={img} type="button" className="preset" style={{ flex: "0 0 auto", width: 84, alignItems: "center" }} aria-pressed={form.image === img}
                onClick={() => setForm({ ...form, image: img })}>
                <PrinterArt kind={img} />
                <span>{img}</span>
              </button>
            ))}
          </div>
        </div>
        <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
          <legend className="field-label">Hub defaults for this printer</legend>
          <span className="field-hint">Pre-selected when someone picks this printer. Only options the printer reports are offered.</span>
          {capsError && <span className="field-error">Capabilities unavailable: {capsError}</span>}
          {caps && (
            <div className="form-grid" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 8 }}>
              {([
                ["color_mode", "Color", caps.color_modes],
                ["sides", "Sides", caps.sides],
                ["media", "Paper size", caps.media],
                ["quality", "Quality", caps.qualities],
              ] as [keyof Settings, string, Choice[]][]).filter(([, , opts]) => opts.length > 1).map(([key, label, opts]) => (
                <div className="field" key={key}>
                  <label htmlFor={`d-${key}`}>{label}</label>
                  <select id={`d-${key}`} className="select" value={(defaults[key] as string) ?? ""}
                    onChange={(e) => setDefaults({ ...defaults, [key]: e.target.value || undefined })}>
                    <option value="">Printer's own default</option>
                    {opts.map((o) => <option key={o.key} value={o.key}>{o.label}</option>)}
                  </select>
                </div>
              ))}
            </div>
          )}
        </fieldset>
        <div className="field">
          <label htmlFor="pnotes">Admin notes</label>
          <textarea id="pnotes" className="textarea" rows={3} maxLength={1000} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
          <span className="field-hint">Model/serial, IP address, supply part numbers. Only visible to administrators.</span>
        </div>
      </div>
    </Dialog>
  );
}

function ConnectQueue({ queue, onClose, onSaved }: { queue: Queue; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(queue.info || queue.queue_name);
  const [location, setLocation] = useState(queue.location);
  const [image, setImage] = useState("laser");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await post("/api/admin/printers", { queue_name: queue.queue_name, display_name: name, location, image });
      toast({ title: "Printer connected", body: "Refresh it to read capabilities, then print a test page." });
      onSaved();
    } catch (e: any) {
      toast({ title: "Not connected", body: e.message, tone: "bad" });
      setBusy(false);
    }
  };
  return (
    <Dialog title="Connect printer" eyebrow={queue.queue_name} size="sm" onClose={onClose} busy={busy}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy || !name.trim()}>{busy ? <Spinner /> : "Connect"}</button>
      </>}>
      <div className="stack">
        <p className="subtle">{queue.make_model} · {queue.connection}</p>
        <div className="field">
          <label htmlFor="cn">Friendly name</label>
          <input id="cn" className="input" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="cl">Location</label>
          <input id="cl" className="input" maxLength={80} value={location} onChange={(e) => setLocation(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="ci">Illustration</label>
          <select id="ci" className="select" value={image} onChange={(e) => setImage(e.target.value)}>
            {IMAGES.map((i) => <option key={i} value={i}>{i}</option>)}
          </select>
        </div>
      </div>
    </Dialog>
  );
}
