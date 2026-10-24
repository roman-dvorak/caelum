<script setup lang="ts">
import DiagramBox from './DiagramBox.vue'
</script>

<template>
  <figure class="cd">
    <svg viewBox="0 0 800 280" role="img" aria-labelledby="cd-data-title">
      <title id="cd-data-title">
        Frames go to the camera's disk, which is a rotating cache; today's files are uploaded about every minute and
        everything every 30 minutes; retention deletes the oldest local files by age, or sooner when space runs
        low, uploaded ones first.
      </title>
      <defs>
        <marker id="cd-data-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" class="cd-head" />
        </marker>
      </defs>

      <DiagramBox :x="20" :y="50" :w="120" :h="90" title="Capture" :lines="['every 30–60 s']" />
      <DiagramBox :x="185" :y="40" :w="190" :h="110" title="Camera disk" :lines="['rotating cache', 'thumbnails, raw,', 'keograms, overlays']" />
      <DiagramBox :x="465" :y="40" :w="160" :h="110" title="Storage server" :lines="['permanent archive']" accent />
      <DiagramBox :x="665" :y="50" :w="115" :h="90" title="Viewer" :lines="['browse', 'and download']" />

      <path d="M140 95 H183" class="cd-edge" marker-end="url(#cd-data-arrow)" />
      <path d="M375 72 H463" class="cd-edge" marker-end="url(#cd-data-arrow)" />
      <text x="420" y="62" text-anchor="middle" class="cd-lbl">today, ~1 min</text>
      <path d="M375 120 H463" class="cd-edge" marker-end="url(#cd-data-arrow)" />
      <text x="420" y="110" text-anchor="middle" class="cd-lbl">all, 30 min</text>
      <path d="M625 95 H663" class="cd-edge" marker-end="url(#cd-data-arrow)" />

      <!-- retention -->
      <path d="M280 150 V188" class="cd-edge cd-dash" marker-end="url(#cd-data-arrow)" />
      <rect x="185" y="190" width="440" height="72" rx="8" class="cd-box cd-dash-box" />
      <text x="405" y="214" text-anchor="middle" class="cd-t">Retention</text>
      <text x="405" y="234" text-anchor="middle" class="cd-s">oldest first, by a set age — sooner when space runs low;</text>
      <text x="405" y="251" text-anchor="middle" class="cd-s">uploaded files go before those the server lacks</text>
    </svg>
    <figcaption>Where frames go, and when the camera forgets them. Intervals are the defaults; the age and space limits are settings.</figcaption>
  </figure>
</template>
