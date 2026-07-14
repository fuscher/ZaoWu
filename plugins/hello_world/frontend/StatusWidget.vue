<template>
  <span class="hello-status-widget" :title="'hello_world plugin active'">
    🟢 HW
  </span>
</template>

<style scoped>
.hello-status-widget {
  font-size: 10px;
  color: var(--text-tertiary);
  background: var(--bg-glass);
  padding: 1px 6px;
  border-radius: 4px;
  border: 1px solid var(--border-glass);
  margin-right: 4px;
}
</style>
