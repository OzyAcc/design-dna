// Results: every submitted batch, with live counts by state.
import { Link } from "react-router-dom";
import { api, type Run } from "../api";
import { STATUS_LABEL, StatusDot, useAsync } from "../lib";

export default function Runs() {
  const { data, error, loading } = useAsync(() => api.get<Run[]>("/api/runs"), []);
  return (
    <>
      <div className="page-head"><div><span className="label">Results</span><h1>Runs</h1><p className="lede">Reopen any batch you generated. Outputs keep their frozen inputs, template version, files and checks.</p></div></div>
      {error && <div className="notice bad">{error}</div>}
      {loading && !data && <p className="muted">Loading…</p>}
      {data && data.length === 0 && <div className="empty"><h2>No runs yet</h2><p className="muted">Select templates and products in the library, review the content, then generate.</p><div className="row"><Link className="btn" to="/templates">Open the library</Link></div></div>}
      {data && data.length > 0 && (
        <table className="data">
          <thead><tr><th>Run</th><th>Status</th><th>Outputs</th><th>Submitted</th></tr></thead>
          <tbody>{data.map((r) => (
            <tr key={r.id}>
              <td><Link to={`/runs/${r.id}`}><strong>{r.name}</strong></Link></td>
              <td><span className="row" style={{ gap: 6 }}><StatusDot status={r.status} />{STATUS_LABEL[r.status] || r.status}</span></td>
              <td className="small">{Object.entries(r.counts).map(([k, v]) => `${v} ${STATUS_LABEL[k]?.toLowerCase() || k}`).join(" · ")}</td>
              <td className="small">{new Date(r.created_at).toLocaleString()}</td>
            </tr>))}</tbody>
        </table>
      )}
    </>
  );
}
