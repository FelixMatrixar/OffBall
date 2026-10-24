import { useId, useRef, useState, type ReactNode } from 'react';
import { download, pngBlob, snapshotSvg, svgBlob, toCsv } from '../../lib/export';
import { Chip } from '../ui';

interface ChartFrameProps {
  title: string;
  /** The chart's text equivalent (PRD 16.6, VIS-6). */
  summary: string;
  columns: readonly string[];
  rows: readonly (readonly (string | number)[])[];
  /** File name stem for exports. */
  name: string;
  /** Sample data, not produced by the pipeline yet: labelled as such. */
  sample?: boolean;
  children: ReactNode;
}

/**
 * Every chart's frame: a title, the chart, a text summary, a data-table view, and exports as CSV, SVG or PNG,
 * each carrying the synthetic-data and AI-generated label (PRD 16.6, 16.8).
 */
export function ChartFrame({ title, summary, columns, rows, name, sample = false, children }: ChartFrameProps) {
  const [table, setTable] = useState(false);
  const area = useRef<HTMLDivElement>(null);
  const summaryId = useId();
  const svg = () => area.current?.querySelector('svg') ?? null;
  const exportSvg = () => {
    const s = svg();
    if (s) download(svgBlob(snapshotSvg(s)), `offball-${name}.svg`);
  };
  const exportPng = async () => {
    const s = svg();
    if (s) download(await pngBlob(snapshotSvg(s)), `offball-${name}.png`);
  };
  return (
    <figure className="chart-frame" style={{ margin: 0 }} aria-describedby={summaryId}>
      <div className="chart-head">
        <h3 className="card-h3" style={{ margin: 0 }}>
          {title}
        </h3>
        <div className="cluster" style={{ gap: 6 }}>
          {sample && <Chip tone="muted">Sample data</Chip>}
          <button type="button" className="btn btn-ghost btn-sm press" aria-pressed={table} onClick={() => setTable((v) => !v)}>
            {table ? 'Chart' : 'Table'}
          </button>
          <details className="export-menu">
            <summary className="btn btn-ghost btn-sm press">Export</summary>
            <div className="export-items">
              <button type="button" className="btn btn-ghost btn-sm press" onClick={() => download(toCsv(columns, rows), `offball-${name}.csv`)}>
                CSV
              </button>
              <button type="button" className="btn btn-ghost btn-sm press" onClick={exportSvg} disabled={table}>
                SVG
              </button>
              <button type="button" className="btn btn-ghost btn-sm press" onClick={() => void exportPng()} disabled={table}>
                PNG
              </button>
            </div>
          </details>
        </div>
      </div>
      <div ref={area}>
        {table ? (
          <div className="chart-table-wrap">
            <table className="chart-table">
              <caption className="sr-only">{title}</caption>
              <thead>
                <tr>
                  {columns.map((c) => (
                    <th key={c} scope="col">
                      {c}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    {r.map((v, j) => (
                      <td key={j}>{v}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          children
        )}
      </div>
      <figcaption id={summaryId} className="chart-summary">
        {summary}
      </figcaption>
    </figure>
  );
}
