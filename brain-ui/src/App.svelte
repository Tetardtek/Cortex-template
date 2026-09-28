<script lang="ts">
  import Sidebar from './lib/Sidebar.svelte'
  import Dashboard from './views/Dashboard.svelte'
  import DocsView from './views/DocsView.svelte'
  import CosmosView from './views/CosmosView.svelte'
  import PlaceholderView from './views/PlaceholderView.svelte'

  let currentView = $state('dashboard')
</script>

<Sidebar bind:currentView />

<main class="flex-1 overflow-auto">
  {#if currentView === 'dashboard'}
    <Dashboard />
  {:else if currentView === 'docs'}
    <DocsView />
  {:else if currentView === 'cosmos'}
    <CosmosView />
  {:else}
    <PlaceholderView name={currentView} />
  {/if}
</main>
