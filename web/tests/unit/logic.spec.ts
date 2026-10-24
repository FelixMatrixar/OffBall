// The logic under the pictures: the feed store, frame interpolation, the control field, colour and kit checks,
// label layout, the easing the canvas shares with CSS, adaptive density, and the evaluation screen's statistics.
import { expect, test } from '@playwright/test';
import { bezier, parseEasing } from '../../src/components/pitch/render2d';
import { labelBox, layoutLabels } from '../../src/components/pitch/labels';
import { contrast, deltaE, parseColor, simulate, VISIONS } from '../../src/lib/color';
import { cleanHidden, groupsIn, learnedDensity, listOf, withoutHidden } from '../../src/lib/density';
import { ECE_TARGET, FIDELITY_RESULTS, GATES, KS_GATE, RELIABILITY_RESULTS, ece, frameReport, ks } from '../../src/lib/eval';
import { FrameBuffer } from '../../src/lib/feed/frames';
import { FeedStore } from '../../src/lib/feed/store';
import type { Overlay, TrackedFrame } from '../../src/lib/feed/types';
import { chains, contours, controlField, gapControl, type Grid, type Segment } from '../../src/lib/field';
import { checkFixture, LEAGUE, MIN_DELTA, MIN_PITCH_CONTRAST } from '../../src/lib/kits';

const frame = (id: number, t_ms: number, x: number): TrackedFrame => ({ period: 2, frame_id: id, t_ms, ball: [x, 34, 0.11], players: { 'kes-09': [x, 34, 0] } });

test.describe('FrameBuffer', () => {
  test('keeps frames in time order, ignores duplicates, and passes through every frame', () => {
    const b = new FrameBuffer();
    b.add(frame(3, 120, 3));
    b.add(frame(1, 40, 1));
    b.add(frame(2, 80, 2));
    expect(b.add(frame(2, 80, 2))).toBe(false);
    expect(b.all.map((f) => f.frame_id)).toEqual([1, 2, 3]);
    expect(b.sample(80)!.pos['kes-09'][0]).toBeCloseTo(2, 5);
    const mid = b.sample(60)!.pos['kes-09'][0];
    expect(mid).toBeGreaterThan(1);
    expect(mid).toBeLessThan(2);
  });

  test('never extrapolates more than 200 ms past the newest frame', () => {
    const b = new FrameBuffer();
    for (let i = 0; i < 5; i++) b.add(frame(i, i * 40, i));
    const at200 = b.sample(160 + 200)!.pos['kes-09'][0];
    const at2000 = b.sample(160 + 2000)!.pos['kes-09'][0];
    expect(at2000).toBeCloseTo(at200, 6);
  });
});

test.describe('FeedStore', () => {
  const overlay = (patch: Partial<Overlay> = {}): Overlay =>
    ({
      schema_version: '2.0',
      overlay_id: 'm07-o9001',
      rev: 1,
      match_id: 'm07',
      period: 2,
      t_start_ms: 1_000_000,
      t_end_ms: 1_005_000,
      kind: 'caption',
      layer: 'dom',
      priority: 1,
      mode: 'casual',
      anchors: {},
      text: { en: 'First' },
      a11y_text: { en: 'First' },
      evidence_ids: ['m07-e0912'],
      approval: 'auto',
      ai_generated: true,
      labels: ['ai-generated'],
      ...patch,
    }) as Overlay;
  const upsert = (o: Overlay) => ({ type: 'overlay.upsert' as const, match_id: 'm07', overlay: o, sent_at: '2026-10-24T15:00:00Z' });
  const filter = { mode: 'casual' as const, whatIf: false, fav: 'kes-09' };

  test('keeps the newest revision, whatever order revisions arrive in', () => {
    const s = new FeedStore('test-revs');
    s.ingest(upsert(overlay({ rev: 2, text: { en: 'Second' } })));
    s.ingest(upsert(overlay({ rev: 1 })));
    expect(s.overlays.get('m07-o9001')!.text.en).toBe('Second');
  });

  test('shows a graphic only while it is on, approved and in the viewer’s mode', () => {
    const s = new FeedStore('test-active');
    s.ingest(upsert(overlay()));
    s.ingest(upsert(overlay({ overlay_id: 'm07-o9002', approval: 'pending' })));
    s.ingest(upsert(overlay({ overlay_id: 'm07-o9003', mode: 'analyst' })));
    expect(s.active(1_002_000, filter).map((a) => a.overlay.overlay_id)).toEqual(['m07-o9001']);
    expect(s.active(999_999, filter)).toEqual([]);
    expect(s.active(1_005_000, filter)).toEqual([]);
  });

  test('holds a retracted graphic with its correction for 3 s, then removes it', () => {
    const s = new FeedStore('test-retract');
    s.ingest(upsert(overlay()));
    s.ingest({ type: 'overlay.retract', match_id: 'm07', overlay_id: 'm07-o9001', reason: 'correction', sent_at: '2026-10-24T15:00:01Z' });
    expect(s.active(1_002_000, filter)[0].retraction?.reason).toBe('correction');
    s.retractions.get('m07-o9001')!.at -= 3_500;
    expect(s.active(1_002_000, filter)).toEqual([]);
  });

  test('drops graphics that arrive after their moment in a live feed', () => {
    const s = new FeedStore('test-late');
    s.live = true;
    s.ingest({ type: 'clock.sync', match_id: 'm07', period: 2, t_ms: 1_010_000, speed: 1, server_time: '2026-10-24T15:00:10Z' });
    s.ingest(upsert(overlay()));
    expect(s.overlays.size).toBe(0);
    expect(s.dropped).toBe(1);
  });

  test('reads the score from status messages at any moment', () => {
    const s = new FeedStore('test-score');
    const status = (t_ms: number, kes: number) => ({ type: 'match.status' as const, match_id: 'm07', status: 'in_play' as const, period: 2, t_ms, score: { kes, ash: 0 }, sent_at: '2026-10-24T15:00:00Z' });
    s.ingest(status(2_000, 1));
    s.ingest(status(1_000, 0));
    expect(s.scoreAt(1_500)).toEqual({ kes: 0, ash: 0 });
    expect(s.scoreAt(2_500)).toEqual({ kes: 1, ash: 0 });
  });
});

test.describe('the control field', () => {
  const grid: Grid = { cols: 21, rows: 14 };
  const field = controlField(
    [
      { team: 'kes', x: 25, y: 34 },
      { team: 'ash', x: 80, y: 34 },
    ],
    grid,
  );

  test('is a probability, Kestrel Bay’s near their player and Ashmoor’s near theirs', () => {
    for (const p of field) {
      expect(p).toBeGreaterThanOrEqual(0);
      expect(p).toBeLessThanOrEqual(1);
    }
    const at = (x: number, y: number) => field[Math.floor((y / 68) * grid.rows) * grid.cols + Math.floor((x / 105) * grid.cols)];
    expect(at(25, 34)).toBeGreaterThan(0.5);
    expect(at(80, 34)).toBeLessThan(0.5);
    expect(gapControl(field, grid)).toBeGreaterThanOrEqual(0);
    expect(gapControl(field, grid)).toBeLessThanOrEqual(1);
  });

  test('traces its 50% contour between the two players', () => {
    const segs = contours(field, grid, 0.5);
    expect(segs.length).toBeGreaterThan(0);
    for (const [x] of segs.flat()) {
      expect(x).toBeGreaterThan(25);
      expect(x).toBeLessThan(80);
    }
  });

  test('joins its contour segments into lines, using every segment once', () => {
    const segs = contours(field, grid, 0.5);
    const lines = chains(segs);
    // Two players: one boundary from touchline to touchline, drawn as a single smooth line.
    expect(lines).toHaveLength(1);
    expect(lines[0]).toHaveLength(segs.length + 1);
    // Consecutive points are neighbouring crossings, never a jump across the pitch.
    for (let i = 1; i < lines[0].length; i++) expect(Math.hypot(lines[0][i][0] - lines[0][i - 1][0], lines[0][i][1] - lines[0][i - 1][1])).toBeLessThan(8);
  });

  test('closes a contour that comes back to its start', () => {
    const square: Segment[] = [
      [[0, 0], [1, 0]],
      [[1, 1], [1, 0]],
      [[1, 1], [0, 1]],
      [[0, 1], [0, 0]],
    ];
    const [loop] = chains(square);
    expect(loop).toHaveLength(5);
    expect(loop[loop.length - 1]).toEqual(loop[0]);
  });
});

test.describe('colour', () => {
  test('contrast and colour difference behave as defined', () => {
    expect(contrast(parseColor('#000000'), parseColor('#ffffff'))).toBeCloseTo(21, 1);
    expect(deltaE(parseColor('#4da6ff'), parseColor('#4da6ff'))).toBe(0);
    expect(simulate(parseColor('#4da6ff'), 'typical')).toEqual(parseColor('#4da6ff'));
  });

  test('every fixture in the league stays distinguishable for every viewer, on dark and light pitches', () => {
    const ids = Object.keys(LEAGUE);
    const failures: string[] = [];
    for (const pitch of ['#14301f', '#dcede0']) {
      for (const home of ids) {
        for (const away of ids) {
          if (home === away) continue;
          const r = checkFixture(home, away, pitch);
          // A pattern is the last resort; anything else must clear the colour-difference bar under all four visions.
          if (r.decision !== 'pattern added' && r.minDelta < MIN_DELTA) failures.push(`${home} v ${away} on ${pitch}: ${r.minDelta.toFixed(3)}`);
          for (const c of [r.home.colour, r.away.colour]) if (contrast(parseColor(c), parseColor(pitch)) < MIN_PITCH_CONTRAST - 0.01) failures.push(`${c} on ${pitch}`);
        }
      }
    }
    expect(failures.slice(0, 5)).toEqual([]);
    expect(VISIONS).toHaveLength(4);
  });
});

test.describe('label layout', () => {
  const dots: [number, number][] = [];

  test('puts two labels on one anchor apart', () => {
    const memory = new Map<string, number>();
    const out = layoutLabels(
      [
        { key: 'a', anchor: [500, 300], text: 'No. 9 Velmar', size: 20 },
        { key: 'b', anchor: [500, 300], text: 'Sprint 32.2 km/h', size: 20, dy: 40 },
      ],
      dots,
      memory,
    );
    const [a, b] = out.map((l) => labelBox(l.x, l.y, l.text, 20));
    const overlap = Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0)) * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
    expect(overlap).toBe(0);
  });

  test('steers around fixed labels and stays on the pitch', () => {
    const fixed = labelBox(500, 274, 'Gap zone +12 pts', 21);
    const bounds = { x0: -30, y0: -30, x1: 1080, y1: 710 };
    const [l] = layoutLabels([{ key: 'tag', anchor: [500, 300], text: 'No. 5 Hendricx', size: 20 }], dots, new Map(), [fixed], bounds);
    const box = labelBox(l.x, l.y, l.text, 20);
    expect(Math.max(0, Math.min(box.x1, fixed.x1) - Math.max(box.x0, fixed.x0)) * Math.max(0, Math.min(box.y1, fixed.y1) - Math.max(box.y0, fixed.y0))).toBe(0);
    const [edge] = layoutLabels([{ key: 'edge', anchor: [1060, -20], text: 'No. 7 Quillan', size: 20 }], dots, new Map(), [], bounds);
    const e = labelBox(edge.x, edge.y, edge.text, 20);
    expect(e.y0).toBeGreaterThanOrEqual(bounds.y0);
    expect(e.x1).toBeLessThanOrEqual(bounds.x1);
  });
});

test.describe('easing', () => {
  test('a cubic-bezier starts at 0, ends at 1 and solves like the browser', () => {
    const standard = bezier(0.2, 0, 0, 1);
    expect(standard(0)).toBe(0);
    expect(standard(1)).toBe(1);
    let last = 0;
    for (let u = 0.05; u < 1; u += 0.05) {
      const v = standard(u);
      expect(v).toBeGreaterThanOrEqual(last);
      last = v;
    }
    // The linear curve maps time to itself; ease-in-out is symmetric about the middle.
    expect(bezier(0, 0, 1, 1)(0.37)).toBeCloseTo(0.37, 4);
    expect(bezier(0.42, 0, 0.58, 1)(0.5)).toBeCloseTo(0.5, 4);
    expect(parseEasing('cubic-bezier(0.34, 1.56, 0.64, 1)')(0.5)).toBeGreaterThan(1);
    expect(parseEasing('linear')(0.3)).toBeCloseTo(0.3, 6);
  });
});

test.describe('the evaluation statistics', () => {
  test('KS is the widest gap between two cumulative distributions, counting ties on both sides at once', () => {
    expect(ks([1, 2, 3, 4], [1, 2, 3, 4])).toBe(0);
    expect(ks([1, 2, 3, 4], [5, 6, 7, 8])).toBe(1);
    expect(ks([1, 2, 3, 4], [3, 4, 5, 6])).toBe(0.5);
    expect(ks([1, 1, 2, 2], [1, 2, 2, 2])).toBeCloseTo(0.25, 10);
  });

  test('calibration error weights each bin by how many predictions it holds', () => {
    expect(ece([{ predicted: 0.2, observed: 0.2, n: 10 }])).toBe(0);
    expect(ece([{ predicted: 0.2, observed: 0.3, n: 100 }, { predicted: 0.6, observed: 0.6, n: 300 }])).toBeCloseTo(0.025, 10);
  });

  test('the sample data is football-shaped and passes the gates the page says it does', () => {
    for (const f of FIDELITY_RESULTS) {
      expect(f.ks, f.metric).toBeLessThanOrEqual(KS_GATE);
      expect(Math.min(...f.synthetic, ...f.calibration), f.metric).toBeGreaterThan(0);
      expect(f.synthetic).toEqual([...f.synthetic].sort((a, b) => a - b));
    }
    expect(GATES.filter((g) => g.status !== 'pass')).toEqual([]);
    expect(RELIABILITY_RESULTS.find((r) => r.name === 'Space value')!.ece).toBeLessThanOrEqual(ECE_TARGET);
  });

  test('a frame report finds the display rate, the dropped frames and the 95th percentile', () => {
    // 60 Hz, with two frames that each missed one refresh.
    const r = frameReport([...Array<number>(98).fill(16.7), 33.4, 33.4], Array<number>(100).fill(2));
    expect(r.hz).toBe(60);
    expect(r.frames).toBe(100);
    expect(r.dropped).toBe(2);
    expect(r.p95Ms).toBeCloseTo(16.7, 5);
    expect(r.workP95Ms).toBe(2);
  });
});

test.describe('adaptive density', () => {
  const item = (kind: Overlay['kind']) => ({ overlay: { kind } as Overlay });

  test('steps a mode down one level once two groups are hidden, and only while Adapt is on', () => {
    expect(learnedDensity('standard', ['runs'], true)).toBe('standard');
    expect(learnedDensity('standard', ['runs', 'tags'], true)).toBe('minimal');
    expect(learnedDensity('rich', ['runs', 'tags'], true)).toBe('standard');
    expect(learnedDensity('minimal', ['runs', 'tags', 'line'], true)).toBe('minimal');
    expect(learnedDensity('standard', ['runs', 'tags'], false)).toBe('standard');
  });

  test('takes hidden groups off the pitch and leaves captions, cards and charts', () => {
    const items = [item('run_arrow'), item('player_tag'), item('badge'), item('caption'), item('stat_card'), item('gap_ring')];
    const kept = withoutHidden(items, new Set(['runs', 'tags'] as const)).map((a) => a.overlay.kind);
    expect(kept).toEqual(['caption', 'stat_card', 'gap_ring']);
    expect(withoutHidden(items, new Set())).toBe(items);
  });

  test('offers the groups a mode draws, the field always, in a fixed order', () => {
    expect(groupsIn(['caption', 'player_tag', 'run_arrow', 'run_arrow'])).toEqual(['field', 'runs', 'tags']);
    expect(groupsIn([])).toEqual(['field']);
  });

  test('lists groups in a sentence and cleans what storage gives back', () => {
    expect(listOf(['runs'])).toBe('Runs');
    expect(listOf(['runs', 'tags'])).toBe('Runs and player tags');
    expect(listOf(['field', 'runs', 'tags'])).toBe('Space field, runs and player tags');
    expect(cleanHidden({ casual: ['runs', 'runs', 'nonsense'], learn: [], analyst: 'tags' })).toEqual({ casual: ['runs'] });
    expect(cleanHidden(null)).toEqual({});
  });
});
