<script setup lang="ts">
import DiagramBox from './DiagramBox.vue'
</script>

<template>
  <figure class="cd">
    <svg viewBox="0 0 800 340" role="img" aria-labelledby="cd-sys-title">
      <title id="cd-sys-title">
        The camera captures and uploads to a storage server; Caelum Viewer reads the archive, or the camera directly;
        the operator controls the camera through its web interface.
      </title>
      <defs>
        <marker id="cd-sys-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0 L10 5 L0 10 z" class="cd-head" />
        </marker>
      </defs>

      <!-- camera -->
      <rect x="20" y="30" width="230" height="200" rx="12" class="cd-group" />
      <text x="40" y="58" class="cd-t">Camera</text>
      <text x="40" y="76" class="cd-s">Raspberry Pi under the dome</text>
      <DiagramBox :x="40" :y="90" :w="190" :h="54" title="Capture engine" :lines="['exposure, storage, plugins']" accent />
      <DiagramBox :x="40" :y="158" :w="190" :h="54" title="Web interface" :lines="['control & live view']" />

      <DiagramBox :x="340" :y="70" :w="190" :h="110" title="Storage server" :lines="['permanent archive', 'S3 or a web server']" />
      <DiagramBox :x="600" :y="70" :w="180" :h="110" title="Caelum Viewer" :lines="['browse, play, download', 'viewer.caelum.', 'astrometers.eu']" accent />

      <DiagramBox :x="40" :y="276" :w="190" :h="48" title="You" :lines="['on the local network']" />
      <DiagramBox :x="600" :y="276" :w="180" :h="48" title="Anyone" :lines="['any browser, anywhere']" />

      <!-- upload -->
      <path d="M230 117 H338" class="cd-edge" marker-end="url(#cd-sys-arrow)" />
      <text x="285" y="108" class="cd-lbl" text-anchor="middle">upload</text>
      <!-- archive to viewer -->
      <path d="M530 125 H598" class="cd-edge" marker-end="url(#cd-sys-arrow)" />
      <text x="565" y="116" class="cd-lbl" text-anchor="middle">frames</text>
      <!-- operator to web UI -->
      <path d="M135 274 V214" class="cd-edge" marker-start="url(#cd-sys-arrow)" marker-end="url(#cd-sys-arrow)" />
      <text x="145" y="250" class="cd-lbl">https</text>
      <!-- visitors to viewer -->
      <path d="M690 274 V182" class="cd-edge" marker-end="url(#cd-sys-arrow)" />
      <text x="700" y="232" class="cd-lbl">open</text>
      <!-- direct mode -->
      <path d="M640 182 V250 H215 V232" class="cd-edge cd-dash" marker-end="url(#cd-sys-arrow)" />
      <text x="430" y="243" class="cd-lbl" text-anchor="middle">or straight from the camera, on the local network</text>
    </svg>
    <figcaption>The parts of a caelum installation and how data moves between them.</figcaption>
  </figure>
</template>
