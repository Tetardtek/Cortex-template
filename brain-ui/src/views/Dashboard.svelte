<script lang="ts">

  // Les compteurs viennent du moteur, pas d'un instantané écrit à la main : il
  // annonçait « 82 agents, 20 free / 33 pro » et « 4 types » — des paliers
  // supprimés et des nombres faux chez chaque fork. Sans source, pas
  // de compteur : « Sessions » et « Scripts » n'en avaient pas.
  const API = import.meta.env.VITE_BRAIN_API ?? ''
  let nbAgents = $state<number | null>(null)
  let nbDocs = $state<number | null>(null)
  $effect(() => {
    fetch(`${API}/agents`).then((r) => r.json())
      .then((l) => { nbAgents = l.filter((a: { distributable: boolean }) => a.distributable).length })
      .catch(() => {})
    fetch(`${API}/docs`).then((r) => r.json())
      .then((d) => { nbDocs = (d.docs ?? []).length })
      .catch(() => {})
  })
  const stats = $derived([
    { label: 'Agents', value: nbAgents ?? '—', sub: 'dans ce brain', color: 'var(--accent)' },
    { label: 'Docs', value: nbDocs ?? '—', sub: 'pages humaines', color: 'var(--yellow)' },
  ])

  // Les intentions actives et les dernières sessions viennent de la base. Elles
  // venaient d'un instantané écrit à la main — les projets et l'activité de
  // mars de l'owner, montrés à chaque fork comme si c'était son brain.
  type Intention = { id: string; title: string; project: string | null; status: string }
  type Claim = { sess_id: string; scope: string | null; status: string; result: string | null; opened_at: string }
  let intentions = $state<Intention[] | null>(null)
  let sessions = $state<Claim[] | null>(null)
  // Une panne n'est pas une base vide : un 401/403 (moteur derrière un jeton,
  // un proxy) ou un moteur arrêté affichaient « aucune intention » et « tape
  // brain boot » — deux affirmations fausses (relecture du 28/09).
  let erreurIntentions = $state('')
  let erreurSessions = $state('')
  const lire = (url: string) =>
    fetch(url).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
  $effect(() => {
    lire(`${API}/intentions?status=active`)
      .then((l) => { intentions = l.slice(0, 8) })
      .catch((e) => { erreurIntentions = `Le moteur ne répond pas (${e.message ?? e})`; intentions = [] })
    lire(`${API}/bsi/claims`)
      .then((l) => { sessions = l.slice(0, 6) })
      .catch((e) => { erreurSessions = `Le moteur ne répond pas (${e.message ?? e})`; sessions = [] })
  })
  // Les heures de la base sont en UTC : le dire, plutôt que les laisser lire
  // comme des heures locales.
  const jour = (iso: string) => (iso ? String(iso).slice(0, 16).replace('T', ' ') + ' UTC' : '')
</script>

<div class="p-8 max-w-6xl">
  <header class="mb-8">
    <h1 class="text-2xl font-bold">Dashboard</h1>
    <p class="text-[var(--text-secondary)] text-sm mt-1">Vue d'ensemble de votre brain</p>
  </header>

  <!-- Stats cards -->
  <div class="grid grid-cols-2 gap-4 mb-8">
    {#each stats as stat}
      <div class="bg-[var(--bg-secondary)] rounded-lg p-5 border border-[var(--border)]">
        <div class="text-3xl font-bold" style="color: {stat.color}">{stat.value}</div>
        <div class="text-sm font-medium mt-1">{stat.label}</div>
        <div class="text-xs text-[var(--text-secondary)] mt-0.5">{stat.sub}</div>
      </div>
    {/each}
  </div>

  <div class="grid grid-cols-2 gap-6">
    <!-- Intentions actives -->
    <div class="bg-[var(--bg-secondary)] rounded-lg border border-[var(--border)]">
      <div class="px-5 py-4 border-b border-[var(--border)]">
        <h2 class="text-sm font-semibold">Intentions actives</h2>
      </div>
      <div class="divide-y divide-[var(--border)]">
        {#if intentions === null}
          <div class="px-5 py-3 text-sm text-[var(--text-secondary)]">Chargement...</div>
        {:else if erreurIntentions}
          <div class="px-5 py-3 text-sm text-[var(--text-secondary)]">{erreurIntentions}</div>
        {:else if intentions.length === 0}
          <div class="px-5 py-3 text-sm text-[var(--text-secondary)]">Aucune intention active — elles naissent en travaillant.</div>
        {:else}
          {#each intentions as i}
            <div class="px-5 py-3">
              <div class="text-sm font-medium">{i.title}</div>
              <div class="text-xs text-[var(--text-secondary)]">{i.project ?? '—'}</div>
            </div>
          {/each}
        {/if}
      </div>
    </div>

    <!-- Dernières sessions -->
    <div class="bg-[var(--bg-secondary)] rounded-lg border border-[var(--border)]">
      <div class="px-5 py-4 border-b border-[var(--border)]">
        <h2 class="text-sm font-semibold">Dernières sessions</h2>
      </div>
      <div class="divide-y divide-[var(--border)]">
        {#if sessions === null}
          <div class="px-5 py-3 text-sm text-[var(--text-secondary)]">Chargement...</div>
        {:else if erreurSessions}
          <div class="px-5 py-3 text-sm text-[var(--text-secondary)]">{erreurSessions}</div>
        {:else if sessions.length === 0}
          <div class="px-5 py-3 text-sm text-[var(--text-secondary)]">Aucune session encore — tape « brain boot ».</div>
        {:else}
          {#each sessions as c}
            <div class="px-5 py-3 flex items-center justify-between">
              <div>
                <div class="text-sm">{c.scope ?? c.sess_id}</div>
                <div class="text-xs text-[var(--text-secondary)] mt-0.5">{jour(c.opened_at)}</div>
              </div>
              <span class="text-xs text-[var(--text-secondary)]">{c.status === 'open' ? 'ouverte' : (c.result ?? c.status)}</span>
            </div>
          {/each}
        {/if}
      </div>
    </div>
  </div>
</div>
