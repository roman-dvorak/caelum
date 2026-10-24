<script setup lang="ts">
import DiagramBox from './DiagramBox.vue'
</script>

<template>
  <figure class="cd">
    <svg viewBox="0 0 800 370" role="img" aria-labelledby="cd-pipe-title">
      <title id="cd-pipe-title">
        Sky state sets the exposure preset, the camera captures, the frame is processed and published once; storage,
        plugins, upload and the live view all receive it alongside each other. Measured brightness feeds back into the
        next exposure.
      </title>
      <defs>
        <marker id="cd-pipe-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" class="cd-head" />
        </marker>
      </defs>

      <DiagramBox :x="20" :y="50" :w="160" :h="72" title="Sky state" :lines="['sun & moon', 'at your site']" />
      <DiagramBox :x="215" :y="50" :w="170" :h="72" title="Exposure control" :lines="['preset for the period', '+ feedback']" accent />
      <DiagramBox :x="420" :y="50" :w="150" :h="72" title="Capture" :lines="['camera sensor']" />
      <DiagramBox :x="605" :y="50" :w="175" :h="72" title="Processing" :lines="['darks, statistics,', 'thumbnail, metadata']" />

      <path d="M180 86 H213" class="cd-edge" marker-end="url(#cd-pipe-arrow)" />
      <path d="M385 86 H418" class="cd-edge" marker-end="url(#cd-pipe-arrow)" />
      <path d="M570 86 H603" class="cd-edge" marker-end="url(#cd-pipe-arrow)" />

      <!-- feedback -->
      <path d="M692 50 V24 H300 V48" class="cd-edge cd-dash" marker-end="url(#cd-pipe-arrow)" />
      <text x="496" y="17" class="cd-lbl" text-anchor="middle">measured brightness sets the next exposure</text>

      <!-- publish -->
      <path d="M692 122 V176" class="cd-edge" marker-end="url(#cd-pipe-arrow)" />
      <rect x="20" y="178" width="760" height="40" rx="8" class="cd-bus" />
      <text x="400" y="203" text-anchor="middle" class="cd-s">
        Each frame is published once — everything below runs alongside and never slows capture
      </text>

      <path d="M107 218 V256" class="cd-edge" marker-end="url(#cd-pipe-arrow)" />
      <path d="M302 218 V256" class="cd-edge" marker-end="url(#cd-pipe-arrow)" />
      <path d="M497 218 V256" class="cd-edge" marker-end="url(#cd-pipe-arrow)" />
      <path d="M692 218 V256" class="cd-edge" marker-end="url(#cd-pipe-arrow)" />

      <DiagramBox :x="20" :y="258" :w="175" :h="88" title="Storage" :lines="['thumbnail every frame,', 'raw DNG at night']" />
      <DiagramBox :x="215" :y="258" :w="175" :h="88" title="Plugins" :lines="['keogram, meteor', 'detection, overlay']" />
      <DiagramBox :x="410" :y="258" :w="175" :h="88" title="Upload" :lines="['to the storage server']" />
      <DiagramBox :x="605" :y="258" :w="175" :h="88" title="Live view" :lines="['dashboard and', 'live stream']" />
    </svg>
    <figcaption>What happens to every frame inside the camera.</figcaption>
  </figure>
</template>
