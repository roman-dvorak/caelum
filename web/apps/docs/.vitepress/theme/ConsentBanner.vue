<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import { analyticsEnabled, loadTrackers, setConsent, storedConsent, trackerNames } from './analytics'

// Rendered only on the client: everything here depends on the host and on
// localStorage, neither of which exists during the static build.
const open = ref(false)
const names = trackerNames().join(' and ')

function choose(value: 'granted' | 'denied') {
  open.value = false
  setConsent(value)
}

// The footer's "Cookie settings" button (config.ts) reopens the banner.
function onClick(e: MouseEvent) {
  if ((e.target as Element | null)?.closest?.('.cookie-settings button')) open.value = true
}

onMounted(() => {
  if (!analyticsEnabled() || !names) return
  document.documentElement.classList.add('has-analytics')
  const consent = storedConsent()
  if (consent === 'granted') loadTrackers()
  open.value = consent === null
  document.addEventListener('click', onClick)
})

onBeforeUnmount(() => document.removeEventListener('click', onClick))
</script>

<template>
  <div v-if="open" class="consent" role="dialog" aria-label="Cookie consent">
    <p>
      With your consent, this site uses {{ names }} to see which pages are read
      and how they are used. Both set cookies and send usage data to their
      providers. Nothing is loaded unless you accept.
    </p>
    <div class="consent-actions">
      <button class="consent-btn" @click="choose('denied')">Decline</button>
      <button class="consent-btn consent-accept" @click="choose('granted')">Accept</button>
    </div>
  </div>
</template>

<style scoped>
.consent {
  position: fixed;
  z-index: 100;
  left: 16px;
  right: 16px;
  bottom: 16px;
  max-width: 640px;
  margin: 0 auto;
  padding: 16px 20px;
  display: flex;
  gap: 16px;
  align-items: center;
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  background: var(--vp-c-bg-elv);
  box-shadow: var(--vp-shadow-3);
}
.consent p {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
  color: var(--vp-c-text-2);
}
.consent-actions {
  display: flex;
  gap: 8px;
  flex: none;
}
/* Equal weight for both choices — accepting must not be the easier click. */
.consent-btn {
  padding: 6px 16px;
  border: 1px solid var(--vp-c-brand-1);
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  color: var(--vp-c-brand-1);
}
.consent-btn:hover {
  background: var(--vp-c-brand-soft);
}
@media (max-width: 640px) {
  .consent {
    flex-direction: column;
    align-items: stretch;
  }
  .consent-actions .consent-btn {
    flex: 1;
  }
}
</style>
