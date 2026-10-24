// Computes control fields off the main thread (PRD 16.2): one request per 25 Hz frame.
import { controlField, type Body, type Grid } from '../field';

interface Request {
  key: string;
  bodies: Body[];
  grid: Grid;
}

self.onmessage = (e: MessageEvent<Request[]>) => {
  const results = e.data.map((r) => ({ key: r.key, field: controlField(r.bodies, r.grid) }));
  (self as unknown as Worker).postMessage(
    results,
    results.map((r) => r.field.buffer),
  );
};
