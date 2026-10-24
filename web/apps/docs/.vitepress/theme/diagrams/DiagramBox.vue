<script setup lang="ts">
/** One labelled box of a docs diagram: a bold title and up to a few lines of
 * smaller text, vertically centred. Colours come from the theme tokens in
 * caelum.css, so the same SVG works in light and dark mode. */
withDefaults(
  defineProps<{
    x: number
    y: number
    w: number
    h: number
    title: string
    lines?: string[]
    accent?: boolean
  }>(),
  { lines: () => [], accent: false },
)

const TITLE = 19
const LINE = 17
</script>

<template>
  <g>
    <rect :x="x" :y="y" :width="w" :height="h" rx="8" :class="accent ? 'cd-box cd-accent' : 'cd-box'" />
    <text
      :x="x + w / 2"
      :y="y + (h - TITLE - LINE * lines.length) / 2 + 14"
      text-anchor="middle"
      class="cd-t"
    >{{ title }}</text>
    <text
      v-for="(line, i) in lines"
      :key="i"
      :x="x + w / 2"
      :y="y + (h - TITLE - LINE * lines.length) / 2 + TITLE + LINE * i + 12"
      text-anchor="middle"
      class="cd-s"
    >{{ line }}</text>
  </g>
</template>
