// One requestAnimationFrame for every layer (PRD 16.2: one clock drives every layer). The match clock moves first,
// then each renderer draws that same instant, so the pitch, its labels and the scrubber never disagree by a frame.

export const PRIO = { clock: 0, draw: 1 } as const;

interface Job {
  prio: number;
  fn: (now: number) => void;
  failed: boolean;
}

const jobs: Job[] = [];
let raf = 0;

function run(now: number) {
  raf = 0;
  for (const job of jobs.slice()) {
    try {
      job.fn(now);
    } catch (err) {
      // One broken layer mustn't stop the others; report it once rather than every frame.
      if (!job.failed) console.error(err);
      job.failed = true;
    }
  }
  if (jobs.length) raf = requestAnimationFrame(run);
}

/** Runs `fn` every display frame until the returned function is called. Lower `prio` runs first. */
export function onFrame(fn: (now: number) => void, prio: number = PRIO.draw): () => void {
  const job: Job = { prio, fn, failed: false };
  jobs.push(job);
  jobs.sort((a, b) => a.prio - b.prio);
  if (!raf) raf = requestAnimationFrame(run);
  return () => {
    const i = jobs.indexOf(job);
    if (i >= 0) jobs.splice(i, 1);
    if (!jobs.length && raf) {
      cancelAnimationFrame(raf);
      raf = 0;
    }
  };
}
