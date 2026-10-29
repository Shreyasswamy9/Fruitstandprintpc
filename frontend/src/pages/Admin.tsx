import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import AdminDiagnostics from "./admin/Diagnostics";
import AdminPeople from "./admin/People";
import AdminPresets from "./admin/Presets";
import AdminPrinters from "./admin/Printers";
import AdminQueue from "./admin/Queue";
import AdminSettings from "./admin/Settings";

const TABS = [
  ["queue", "Station queue"],
  ["printers", "Printers"],
  ["presets", "Presets"],
  ["people", "People"],
  ["diagnostics", "Diagnostics"],
  ["settings", "Settings"],
] as const;

export default function AdminPage() {
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <span className="eyebrow">Administration</span>
          <h1>Station admin</h1>
        </div>
      </div>
      <nav className="tabs" aria-label="Admin sections">
        {TABS.map(([path, label]) => (
          <NavLink key={path} to={`/admin/${path}`}>
            {label}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route index element={<Navigate to="queue" replace />} />
        <Route path="queue" element={<AdminQueue />} />
        <Route path="printers" element={<AdminPrinters />} />
        <Route path="presets" element={<AdminPresets />} />
        <Route path="people" element={<AdminPeople />} />
        <Route path="diagnostics" element={<AdminDiagnostics />} />
        <Route path="settings" element={<AdminSettings />} />
        <Route path="*" element={<Navigate to="queue" replace />} />
      </Routes>
    </div>
  );
}
