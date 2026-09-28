<script lang="ts">
  let { currentView = $bindable('dashboard') } = $props()

  const nav = [
    { id: 'dashboard', label: 'Dashboard', icon: '◉' },
    { id: 'docs', label: 'Documentation', icon: '◈' },
    { id: 'cosmos', label: 'Cosmos', icon: '✦' },
    { id: 'sessions', label: 'Sessions', icon: '◇' },
    { id: 'backlog', label: 'Backlog', icon: '▦' },
    { id: 'agents', label: 'Agents', icon: '◆' },
  ]
</script>

<aside class="w-56 bg-[var(--bg-secondary)] border-r border-[var(--border)] flex flex-col">
  <div class="px-4 py-5 border-b border-[var(--border)]">
    <h1 class="text-lg font-semibold text-[var(--accent)] tracking-tight">Brain UI</h1>
    <p class="text-xs text-[var(--text-secondary)] mt-0.5">Cognitive Dashboard</p>
  </div>

  <nav class="flex-1 py-3">
    {#each nav as item}
      <button
        class="w-full px-4 py-2.5 text-left text-sm flex items-center gap-3 transition-colors
          {currentView === item.id
            ? 'bg-[var(--accent)]/10 text-[var(--accent)] border-r-2 border-[var(--accent)]'
            : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'}"
        onclick={() => currentView = item.id}
      >
        <span class="text-base">{item.icon}</span>
        {item.label}
      </button>
    {/each}
  </nav>

  <div class="px-4 py-3 border-t border-[var(--border)] text-xs text-[var(--text-secondary)]">
    <div class="mt-1 opacity-50">brain-ui v2.0 — svelte</div>
  </div>
</aside>
