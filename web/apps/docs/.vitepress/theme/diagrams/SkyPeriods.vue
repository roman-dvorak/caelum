<script setup lang="ts">
/** The five sky periods with the default exposure envelope, cadence and raw
 * policy of each — the defaults from config/default.json. Keep in sync if
 * those defaults change. */
const periods = [
  { name: 'Day', color: '#f2c14e', ink: '#1a1405', sun: 'above −0.8°', exp: '0.1–10 ms', gain: '1–2×', every: '60 s', raw: '—' },
  { name: 'Civil twilight', color: '#e08a3c', ink: '#1a0e03', sun: '−0.8° to −6°', exp: '0.2–100 ms', gain: '1–4×', every: '60 s', raw: '—' },
  { name: 'Nautical', color: '#9a63c4', ink: '#ffffff', sun: '−6° to −12°', exp: '1 ms–2 s', gain: '1–8×', every: '60 s', raw: '—' },
  { name: 'Astronomical', color: '#4f5fc4', ink: '#ffffff', sun: '−12° to −18°', exp: '10 ms–8 s', gain: '1–12×', every: '30 s', raw: 'saved' },
  { name: 'Night', color: '#1c305c', ink: '#ffffff', sun: 'below −18°', exp: '0.1–15 s', gain: '1–16×', every: '30 s', raw: 'saved' },
]
const rows = [
  { key: 'sun', label: 'Sun altitude' },
  { key: 'exp', label: 'Exposure' },
  { key: 'gain', label: 'Gain' },
  { key: 'every', label: 'Frame every' },
  { key: 'raw', label: 'Raw DNG' },
] as const
const X0 = 140
const COL = 128
</script>

<template>
  <figure class="cd">
    <svg viewBox="0 0 800 268" role="img" aria-labelledby="cd-sky-title">
      <title id="cd-sky-title">
        The five sky periods, from day to night, with the default exposure range, gain range, capture interval and raw
        policy of each.
      </title>
      <g v-for="(p, i) in periods" :key="p.name">
        <rect :x="X0 + i * COL" y="20" :width="COL - 4" height="40" rx="6" :fill="p.color" />
        <text :x="X0 + i * COL + (COL - 4) / 2" y="45" text-anchor="middle" class="cd-band" :fill="p.ink">{{ p.name }}</text>
      </g>
      <path d="M140 72 H776" class="cd-edge" marker-end="url(#cd-sky-arrow)" />
      <defs>
        <marker id="cd-sky-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0 0 L10 5 L0 10 z" class="cd-head" />
        </marker>
      </defs>
      <text x="20" y="76" class="cd-lbl">sunset → darkness</text>

      <g v-for="(r, j) in rows" :key="r.key">
        <line x1="20" :x2="776" :y1="92 + j * 34" :y2="92 + j * 34" class="cd-rule" />
        <text x="20" :y="114 + j * 34" class="cd-s cd-strong">{{ r.label }}</text>
        <text
          v-for="(p, i) in periods"
          :key="p.name"
          :x="X0 + i * COL + (COL - 4) / 2"
          :y="114 + j * 34"
          text-anchor="middle"
          :class="r.key === 'raw' && p.raw !== '—' ? 'cd-s cd-strong' : 'cd-s'"
        >{{ p[r.key] }}</text>
      </g>
    </svg>
    <figcaption>
      One evening, left to right; the morning runs the same way back. Ranges are the defaults — every value is a
      setting.
    </figcaption>
  </figure>
</template>
