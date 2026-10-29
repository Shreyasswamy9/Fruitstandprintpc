import { useCallback, useEffect, useState } from "react";
import { get, newKey, patch, post } from "../../api";
import { Chip, Dialog, Spinner, useToast } from "../../components/ui";
import { useHub } from "../../context";
import { dateTime } from "../../lib/format";

interface Person {
  id: number;
  username: string;
  display_name: string;
  role: "employee" | "admin";
  active: boolean;
  must_change_password: boolean;
  last_login_at: number | null;
}

function tempPassword(): string {
  // Readable temporary password; the person must change it at first sign-in.
  return newKey().slice(0, 4) + "-" + newKey().slice(0, 4) + "-" + newKey().slice(0, 4);
}

export default function AdminPeople() {
  const { user } = useHub();
  const toast = useToast();
  const [people, setPeople] = useState<Person[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [issued, setIssued] = useState<{ username: string; password: string } | null>(null);
  const load = useCallback(() => get<{ users: Person[] }>("/api/admin/users").then((r) => setPeople(r.users)), []);
  useEffect(() => {
    load();
  }, [load]);

  const update = async (p: Person, change: Partial<Person>) => {
    try {
      await patch(`/api/admin/users/${p.id}`, change);
      load();
    } catch (e: any) {
      toast({ title: "Not changed", body: e.message, tone: "bad" });
    }
  };
  const reset = async (p: Person) => {
    const password = tempPassword();
    try {
      await post(`/api/admin/users/${p.id}/reset-password`, { password });
      setIssued({ username: p.username, password });
      load();
    } catch (e: any) {
      toast({ title: "Not reset", body: e.message, tone: "bad" });
    }
  };

  return (
    <div className="stack-lg">
      <div className="row-between">
        <p className="muted" style={{ maxWidth: "70ch" }}>
          Each person signs in with their own account, so jobs stay private and cancellations are attributable. New and reset accounts get a
          temporary password that must be changed at first sign-in.
        </p>
        <button className="btn btn-primary" onClick={() => setAdding(true)}>
          Add person
        </button>
      </div>
      <div className="card table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Role</th>
              <th>Status</th>
              <th>Last sign-in</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {people?.map((p) => (
              <tr key={p.id}>
                <td>
                  <b>{p.display_name}</b>
                  <div className="subtle mono">{p.username}</div>
                </td>
                <td>
                  <select className="select" style={{ minHeight: 34, width: 150 }} value={p.role} aria-label={`Role for ${p.username}`}
                    onChange={(e) => update(p, { role: e.target.value as Person["role"] })} disabled={p.id === user.id}>
                    <option value="employee">Employee</option>
                    <option value="admin">Administrator</option>
                  </select>
                </td>
                <td>
                  {p.active ? <Chip tone="ok">Active</Chip> : <Chip tone="neutral">Deactivated</Chip>}
                  {p.must_change_password && <div className="subtle">Temporary password</div>}
                </td>
                <td className="subtle">{dateTime(p.last_login_at)}</td>
                <td>
                  <div className="row" style={{ justifyContent: "flex-end", flexWrap: "nowrap" }}>
                    <button className="btn btn-sm" onClick={() => reset(p)}>
                      Reset password
                    </button>
                    {p.id !== user.id && (
                      <button className="btn btn-sm" onClick={() => update(p, { active: !p.active })}>
                        {p.active ? "Deactivate" : "Reactivate"}
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {adding && <AddPerson onClose={() => setAdding(false)} onDone={(u, pw) => { setAdding(false); setIssued({ username: u, password: pw }); load(); }} />}
      {issued && (
        <Dialog title="Temporary password" size="sm" onClose={() => setIssued(null)} footer={<button className="btn btn-primary" onClick={() => setIssued(null)}>Done</button>}>
          <div className="stack">
            <p className="muted">Give this to <b>{issued.username}</b> in person. It won't be shown again, and they'll choose their own password when they sign in.</p>
            <p className="display mono" style={{ fontSize: "1.6rem", userSelect: "all" }}>{issued.password}</p>
          </div>
        </Dialog>
      )}
    </div>
  );
}

function AddPerson({ onClose, onDone }: { onClose: () => void; onDone: (username: string, password: string) => void }) {
  const toast = useToast();
  const [username, setUsername] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<"employee" | "admin">("employee");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    const password = tempPassword();
    try {
      await post("/api/admin/users", { username, display_name: name, role, password });
      onDone(username, password);
    } catch (e: any) {
      toast({ title: "Not added", body: e.message, tone: "bad" });
      setBusy(false);
    }
  };
  return (
    <Dialog title="Add person" size="sm" onClose={onClose} busy={busy}
      footer={<>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button className="btn btn-primary" onClick={save} disabled={busy || !username.trim()}>{busy ? <Spinner /> : "Add"}</button>
      </>}>
      <div className="stack">
        <div className="field">
          <label htmlFor="nu">Username</label>
          <input id="nu" className="input" autoCapitalize="none" spellCheck={false} maxLength={64} value={username} onChange={(e) => setUsername(e.target.value.trim())} />
          <span className="field-hint">Letters, numbers and . _ - @ (an email address works).</span>
        </div>
        <div className="field">
          <label htmlFor="nn">Display name</label>
          <input id="nn" className="input" maxLength={80} value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="nr">Role</label>
          <select id="nr" className="select" value={role} onChange={(e) => setRole(e.target.value as "employee" | "admin")}>
            <option value="employee">Employee — prints and manages own jobs</option>
            <option value="admin">Administrator — station queue, printers, diagnostics</option>
          </select>
        </div>
      </div>
    </Dialog>
  );
}
