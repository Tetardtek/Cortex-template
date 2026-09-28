<script lang="ts">
  let { name = '' } = $props()

  const viewInfo: Record<string, { title: string; description: string; features: string[] }> = {
    sessions: {
      title: 'Sessions',
      description: 'Visualisez vos sessions BSI : claims actifs, historique, heatmap temporelle.',
      features: ['Session Heatmap', 'Claims timeline', 'Filtrage par type (work/brain/explore/pilote)', 'Duree et scope par session'],
    },
    backlog: {
      title: 'Backlog',
      description: 'Vos visions, intentions et todos — organisees par projet et priorite.',
      features: ['Visions par projet', 'Intentions avec dependances', 'Progression en temps reel', 'Promote intention → sprint'],
    },
    agents: {
      title: 'Agents',
      description: 'Catalogue complet des agents du brain, avec leur portée, leur composition et leurs déclencheurs.',
      features: ['Filtrage par portée et par rôle', 'Graph de composition inter-agents', 'Triggers et conditions', 'Changelog par agent'],
    },
  }

  const info = $derived(viewInfo[name] || { title: name, description: '', features: [] })
</script>

<div class="flex items-center justify-center h-full">
  <div class="max-w-lg text-center">
    <div class="w-16 h-16 rounded-2xl bg-[var(--accent)]/10 flex items-center justify-center mx-auto mb-6">
      <span class="text-3xl text-[var(--accent)]">✦</span>
    </div>

    <h2 class="text-xl font-bold mb-2">{info.title}</h2>
    <p class="text-[var(--text-secondary)] text-sm mb-6">{info.description}</p>

    {#if info.features.length > 0}
      <div class="bg-[var(--bg-secondary)] rounded-lg border border-[var(--border)] p-5 text-left">
        <div class="text-xs font-medium text-[var(--text-secondary)] uppercase tracking-wider mb-3">
          Pistes pour cette vue
        </div>
        <ul class="space-y-2">
          {#each info.features as feature}
            <li class="text-sm flex items-center gap-2">
              <span class="text-[var(--accent)]">◇</span>
              {feature}
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    <div class="mt-6 text-xs text-[var(--text-secondary)]">
      Cette vue n'est pas encore construite dans brain-ui.
    </div>
  </div>
</div>
