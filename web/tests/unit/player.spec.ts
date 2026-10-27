// The match player's own logic: match time across both halves, the broadcast clock, and a what-if as graphics.
import { expect, test } from '@playwright/test';
import type { WhatIf } from '../../src/lib/player/api';
import { clockOf, matchTime } from '../../src/lib/player/clock';
import { GHOST_AFTER_MS, GHOST_BEFORE_MS, whatIfItems } from '../../src/lib/player/whatif';

const periods = [
  { period: 1, duration_ms: 2_760_640, attacks_left_to_right: 'ash' },
  { period: 2, duration_ms: 3_157_280, attacks_left_to_right: 'kes' },
];

test('match time runs both halves end to end', () => {
  const mt = matchTime(periods);
  expect(mt.total).toBe(2_760_640 + 3_157_280);
  expect(mt.toMatch({ period: 2, t_ms: 1_080_000 })).toBe(2_760_640 + 1_080_000);
  expect(mt.toPosition(2_760_640 + 1_080_000)).toEqual({ period: 2, t_ms: 1_080_000 });
  expect(mt.toPosition(10_000)).toEqual({ period: 1, t_ms: 10_000 });
  // Past either end, the position stays on the pitch's clock.
  expect(mt.toPosition(-5)).toEqual({ period: 1, t_ms: 0 });
  expect(mt.toPosition(mt.total + 1000)).toEqual({ period: 2, t_ms: 3_157_280 });
  expect(mt.toMatch({ period: 1, t_ms: 9_999_999 })).toBe(2_760_640);
});

test('the clock reads as a broadcast clock, with stoppage time', () => {
  expect(clockOf({ period: 1, t_ms: 0 })).toBe('0:00');
  expect(clockOf({ period: 2, t_ms: 1_080_000 })).toBe('63:00');
  expect(clockOf({ period: 1, t_ms: 46 * 60_000 + 10_000 })).toBe('45+1:10');
  expect(clockOf({ period: 2, t_ms: 47 * 60_000 })).toBe('90+2:00');
});

test('a what-if becomes dashed ghosts and a ring, timed around the moment', () => {
  const w: WhatIf = {
    candidate_id: 'm07-d0220',
    option_id: 'hold',
    counterfactual_id: 'm07-d0220-cf-hold',
    period: 2,
    t_start_ms: 1_081_440,
    t_measure_ms: 1_084_200,
    numbers: { space_created_m2: 34.1 },
    tracks: { 'kes-09': [[1_081_440, 84.2, 23.1], [1_084_200, 82.4, 24.6]], 'ash-05': [[1_081_440, 85.1, 23.1], [1_084_200, 84.1, 25.2]] },
    ring: { at: [86.4, 23.3], rx_m: 4.5, ry_m: 6, open: false },
  };
  const items = whatIfItems(w);
  expect(items.map((o) => o.kind)).toEqual(['gap_ring', 'ghost', 'ghost']);
  expect(items[0].data).toMatchObject({ shut: true, rx_m: 4.5, ry_m: 6 });
  for (const o of items) {
    expect(o.period).toBe(2);
    expect(o.t_start_ms).toBe(w.t_start_ms - GHOST_BEFORE_MS);
    expect(o.t_end_ms).toBe(w.t_measure_ms + GHOST_AFTER_MS);
  }
  // Ghost tracks are read in seconds of the period, as the renderer's clock is.
  expect(items[1].anchors.player_id).toBe('kes-09');
  expect(items[1].data?.track).toEqual([[1081.44, 84.2, 23.1], [1084.2, 82.4, 24.6]]);
  expect(items[1].counterfactual_id).toBe(w.counterfactual_id);
});
