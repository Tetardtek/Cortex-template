<script lang="ts">
  import { marked } from 'marked'
  import DOMPurify from 'dompurify'

  // La doc VIVANTE du moteur : la liste (`/docs`) et chaque page
  // (`/docs/<nom>.md`), servies depuis `docs/` — générée depuis le brain.
  // Cette vue lisait des copies statiques (`public/docs/`) avec une liste de
  // pages écrite en dur : elles avaient cessé de suivre la doc, et annonçaient
  // encore des paliers supprimés.
  type Doc = { name: string; label: string; group: string; order: number }

  const API = import.meta.env.VITE_BRAIN_API ?? ''
  let docs = $state<Doc[]>([])
  let selected = $state<Doc | null>(null)
  let content = $state('')
  let loading = $state(true)
  let erreur = $state('')

  // Deux clics rapides : la réponse lente de la première page écrasait la
  // seconde, sous le mauvais titre. Seule la DERNIÈRE demande s'affiche.
  let demande = 0
  async function loadDoc(doc: Doc) {
    const ici = ++demande
    selected = doc
    loading = true
    let rendu: string
    try {
      const res = await fetch(`${API}/docs/${doc.name}.md`)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const { content: texte } = await res.json()
      // Ce qui est rendu par {@html} est assaini : une page de docs/ qui
      // porterait du HTML actif (<script>, onerror=, un lien javascript:)
      // s'exécuterait sur l'origine du moteur — qui, sans jeton, a tous les
      // droits. `marked` n'assainit plus rien depuis sa v5.
      rendu = DOMPurify.sanitize(marked(texte) as string)
    } catch (e) {
      const raison = e instanceof Error && e.message.startsWith('HTTP') ? e.message : 'réponse illisible'
      rendu = `<p class="text-[var(--text-secondary)]">Page indisponible (${raison}).</p>`
    }
    if (ici !== demande) return
    content = rendu
    loading = false
  }

  $effect(() => {
    fetch(`${API}/docs`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((data) => {
        docs = data.docs ?? []
        if (docs.length) loadDoc(docs[0])
        else loading = false
      })
      .catch((e) => {
        erreur = `Le moteur ne répond pas (${e}) — bash scripts/brain-engine.sh start`
        loading = false
      })
  })

  // Les groupes dans l'ordre de leur première page.
  const groupes = $derived(
    docs.reduce<{ nom: string; pages: Doc[] }[]>((acc, d) => {
      const g = acc.find((x) => x.nom === d.group)
      if (g) g.pages.push(d)
      else acc.push({ nom: d.group, pages: [d] })
      return acc
    }, []),
  )
</script>

<div class="flex h-full">
  <!-- Doc sidebar -->
  <div class="w-64 bg-[var(--bg-secondary)] border-r border-[var(--border)] overflow-y-auto">
    <div class="px-4 py-4 border-b border-[var(--border)]">
      <h2 class="text-sm font-semibold">Documentation</h2>
      <p class="text-xs text-[var(--text-secondary)] mt-0.5">{docs.length} pages</p>
    </div>
    <nav class="py-2">
      {#each groupes as groupe}
        <p class="px-4 pt-3 pb-1 text-[10px] uppercase tracking-wider text-[var(--text-secondary)]">{groupe.nom}</p>
        {#each groupe.pages as doc}
          <button
            class="w-full px-4 py-2 text-left text-sm transition-colors
              {selected?.name === doc.name
                ? 'bg-[var(--accent)]/10 text-[var(--accent)]'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)]'}"
            onclick={() => loadDoc(doc)}
          >
            {doc.label}
          </button>
        {/each}
      {/each}
    </nav>
  </div>

  <!-- Doc content -->
  <div class="flex-1 overflow-y-auto p-8 max-w-4xl">
    {#if erreur}
      <div class="text-[var(--text-secondary)]">{erreur}</div>
    {:else if loading}
      <div class="text-[var(--text-secondary)]">Chargement...</div>
    {:else}
      <article class="prose prose-invert prose-sm max-w-none
        [&_h1]:text-2xl [&_h1]:font-bold [&_h1]:mb-4 [&_h1]:text-[var(--text-primary)]
        [&_h2]:text-xl [&_h2]:font-semibold [&_h2]:mt-8 [&_h2]:mb-3 [&_h2]:text-[var(--text-primary)]
        [&_h3]:text-lg [&_h3]:font-medium [&_h3]:mt-6 [&_h3]:mb-2 [&_h3]:text-[var(--text-primary)]
        [&_p]:text-[var(--text-secondary)] [&_p]:mb-3 [&_p]:leading-relaxed
        [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:text-[var(--text-secondary)] [&_ul]:mb-3
        [&_ol]:list-decimal [&_ol]:pl-6 [&_ol]:text-[var(--text-secondary)] [&_ol]:mb-3
        [&_li]:mb-1
        [&_code]:bg-[var(--bg-tertiary)] [&_code]:px-1.5 [&_code]:py-0.5 [&_code]:rounded [&_code]:text-[var(--accent)] [&_code]:text-xs
        [&_pre]:bg-[var(--bg-tertiary)] [&_pre]:p-4 [&_pre]:rounded-lg [&_pre]:overflow-x-auto [&_pre]:mb-4
        [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_pre_code]:text-[var(--text-primary)]
        [&_table]:w-full [&_table]:mb-4
        [&_th]:text-left [&_th]:px-3 [&_th]:py-2 [&_th]:border-b [&_th]:border-[var(--border)] [&_th]:text-sm [&_th]:font-medium
        [&_td]:px-3 [&_td]:py-2 [&_td]:border-b [&_td]:border-[var(--border)] [&_td]:text-sm [&_td]:text-[var(--text-secondary)]
        [&_a]:text-[var(--accent)] [&_a]:underline
        [&_blockquote]:border-l-2 [&_blockquote]:border-[var(--accent)] [&_blockquote]:pl-4 [&_blockquote]:italic [&_blockquote]:text-[var(--text-secondary)]
        [&_hr]:border-[var(--border)] [&_hr]:my-6
        [&_strong]:text-[var(--text-primary)]">
        {@html content}
      </article>
    {/if}
  </div>
</div>
