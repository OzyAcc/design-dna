// Results: every submitted batch, with live counts by state.
import { Link } from "react-router-dom";
import { api, type Run } from "../api";
import { STATUS_LABEL, StatusDot, useAsync } from "../lib";
import { EmptyState, Icon, PageHeader } from "../components/ui";

export default function Runs() {
  const { data, error, loading } = useAsync(() => api.get<Run[]>("/api/runs"), []);
  return (
    <>
      <PageHeader eyebrow="Your generated work" title={<>Results<span className="title-dot">.</span></>} description="Review each output, understand its checks and export the work you approve." actions={<Link className="btn secondary" to="/templates"><Icon name="layers" size={16} />Create a new batch</Link>} />
      {error && <div className="notice bad">{error}</div>}
      {loading && !data && <p className="muted">Loading…</p>}
      {data && data.length === 0 && <EmptyState icon="results" title="Your first batch is waiting." actions={<Link className="btn accent" to="/templates">Choose templates<Icon name="arrow" size={16} /></Link>}><p>Select templates from the library, add your products and review the content before you generate.</p></EmptyState>}
      {data && data.length > 0 && (
        <div className="table-wrap"><table className="data">
          <thead><tr><th>Run</th><th>Status</th><th>Outputs</th><th>Submitted</th></tr></thead>
          <tbody>{data.map((r) => (
            <tr key={r.id}>
              <td><Link to={`/runs/${r.id}`}><strong>{r.name}</strong></Link></td>
              <td><span className="row" style={{ gap: 6 }}><StatusDot status={r.status} />{STATUS_LABEL[r.status] || r.status}</span></td>
              <td className="small">{Object.entries(r.counts).map(([k, v]) => `${v} ${STATUS_LABEL[k]?.toLowerCase() || k}`).join(" · ")}</td>
              <td className="small">{new Date(r.created_at).toLocaleString()}</td>
            </tr>))}</tbody>
        </table></div>
      )}
    </>
  );
}
