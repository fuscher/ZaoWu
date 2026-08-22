<script setup lang="ts">
import GitChangesList from './GitChangesList.vue'
import GitCommitPanel from './GitCommitPanel.vue'
import GitTerminal from './GitTerminal.vue'
</script>

<template>
  <div class="git-panel">
    <div class="git-top">
      <div class="git-top-left">
        <GitChangesList />
      </div>
      <div class="git-top-right">
        <GitCommitPanel />
      </div>
    </div>
    <div class="git-bottom">
      <GitTerminal />
    </div>
  </div>
</template>

<style scoped>
.git-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.git-top {
  flex: 7;
  display: flex;
  overflow: hidden;
  min-height: 0;
}

.git-top-left {
  flex: 7;
  min-width: 0;
  border-right: 1px solid var(--border-glass);
}

.git-top-right {
  flex: 3;
  min-width: 0;
}

.git-bottom {
  flex: 2;
  min-height: clamp(120px, 20vh, 280px);
}
</style>
