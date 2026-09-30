<script lang="ts">
  import { onMount, tick } from 'svelte'
  import * as THREE from 'three'

  let container = $state<HTMLDivElement | null>(null)
  let hoveredNode = $state<string | null>(null)
  let selectedPoint = $state<{ id: string; path: string; zone: string; excerpt: string } | null>(null)
  let tooltipX = $state(0)
  let tooltipY = $state(0)
  let totalPoints = $state(0)
  let loading = $state(true)

  // Zone → couleur. Les zones sont celles que l'indexation écrit dans
  // `embeddings.scope` (brain-engine/embed.py, PATH_SCOPES) : kernel, instance,
  // satellite, public. `personal`, `reference`, `project`, `config` étaient des
  // zones d'avant, qu'aucun chunk ne porte plus ; `instance` n'avait pas de
  // couleur et tombait en gris.
  const ZONE_COLORS: Record<string, string> = {
    kernel: '#f25c7a',
    instance: '#89dceb',
    satellite: '#e8c87a',
    public: '#c9a0ff',
  }

  function getZoneColor(zone: string): string {
    return ZONE_COLORS[zone] || '#6b7280'
  }

  const API = import.meta.env.VITE_BRAIN_API ?? ''

  // Le chargement est asynchrone ; `onMount` ne l'est pas. Une fonction
  // `async` passée à `onMount` rend une promesse, et Svelte n'en tire pas le
  // nettoyage : quitter la vue laissait tourner l'animation, l'observateur et
  // le renderer. `construire` rend le nettoyage, `onMount` le branche.
  async function construire(): Promise<(() => void) | undefined> {
    // Fetch real data from brain-engine
    let points: { id: string; path: string; zone: string; label: string; excerpt: string; x: number; y: number; z: number }[] = []

    try {
      const res = await fetch(`${API}/visualize`)
      if (res.ok) {
        const data = await res.json()
        points = data.points || []
      }
    } catch {
      // Fallback: empty
    }

    totalPoints = points.length
    loading = false
    // La div du dessin n'existe qu'une fois `loading` retombé, et Svelte met le
    // DOM à jour APRÈS ce code : sans attendre, `container` était toujours vide
    // et la vue s'arrêtait là — la légende s'affichait, jamais les points.
    await tick()

    if (points.length === 0 || !container) return
    const el: HTMLDivElement = container

    // Compute bounds for normalization
    let minX = Infinity, maxX = -Infinity
    let minY = Infinity, maxY = -Infinity
    let minZ = Infinity, maxZ = -Infinity

    for (const p of points) {
      if (p.x < minX) minX = p.x; if (p.x > maxX) maxX = p.x
      if (p.y < minY) minY = p.y; if (p.y > maxY) maxY = p.y
      if (p.z < minZ) minZ = p.z; if (p.z > maxZ) maxZ = p.z
    }

    const rangeX = maxX - minX || 1
    const rangeY = maxY - minY || 1
    const rangeZ = maxZ - minZ || 1
    const scale = 20 // spread in scene

    // Scene setup
    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#120a1e')
    scene.fog = new THREE.FogExp2('#120a1e', 0.015)

    const camera = new THREE.PerspectiveCamera(60, el.clientWidth / el.clientHeight, 0.1, 200)
    camera.position.set(0, 5, 30)
    camera.lookAt(0, 0, 0)

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(el.clientWidth, el.clientHeight)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    el.appendChild(renderer.domElement)

    // Lights
    scene.add(new THREE.AmbientLight('#404060', 0.4))
    const light1 = new THREE.PointLight('#c9a0ff', 2, 50)
    light1.position.set(15, 15, 15)
    scene.add(light1)
    const light2 = new THREE.PointLight('#9adba8', 1.5, 50)
    light2.position.set(-15, -10, 10)
    scene.add(light2)

    // InstancedMesh for performance (2700+ points)
    const sphereGeo = new THREE.SphereGeometry(0.08, 8, 8)
    const sphereMat = new THREE.MeshPhongMaterial({
      color: '#ffffff',
      emissive: '#ffffff',
      emissiveIntensity: 0.3,
      transparent: true,
      opacity: 0.85,
    })

    const instancedMesh = new THREE.InstancedMesh(sphereGeo, sphereMat, points.length)
    const dummy = new THREE.Object3D()
    const colorAttr = new THREE.InstancedBufferAttribute(new Float32Array(points.length * 3), 3)

    // Store normalized positions for raycasting
    const positions: THREE.Vector3[] = []

    for (let i = 0; i < points.length; i++) {
      const p = points[i]
      const nx = ((p.x - minX) / rangeX - 0.5) * scale
      const ny = ((p.y - minY) / rangeY - 0.5) * scale
      const nz = ((p.z - minZ) / rangeZ - 0.5) * scale

      dummy.position.set(nx, ny, nz)
      dummy.updateMatrix()
      instancedMesh.setMatrixAt(i, dummy.matrix)

      const color = new THREE.Color(getZoneColor(p.zone))
      colorAttr.setXYZ(i, color.r, color.g, color.b)

      positions.push(new THREE.Vector3(nx, ny, nz))
    }

    instancedMesh.instanceColor = colorAttr
    instancedMesh.instanceMatrix.needsUpdate = true
    scene.add(instancedMesh)

    // Star particles background
    const starGeo = new THREE.BufferGeometry()
    const starPositions = new Float32Array(1500)
    for (let i = 0; i < 1500; i++) {
      starPositions[i] = (Math.random() - 0.5) * 80
    }
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPositions, 3))
    const starMat = new THREE.PointsMaterial({ color: '#2d1a45', size: 0.04 })
    scene.add(new THREE.Points(starGeo, starMat))

    // Animation
    let time = 0
    let isDragging = false
    let rotY = 0
    let rotX = 0.15

    el.addEventListener('mousemove', (e) => {
      const rect = el.getBoundingClientRect()
      tooltipX = e.clientX - rect.left
      tooltipY = e.clientY - rect.top

      if (isDragging) {
        rotY += e.movementX * 0.005
        rotX += e.movementY * 0.005
        rotX = Math.max(-1.2, Math.min(1.2, rotX))
      }
    })

    el.addEventListener('mousedown', () => isDragging = true)
    el.addEventListener('mouseup', () => isDragging = false)
    el.addEventListener('mouseleave', () => isDragging = false)

    // Raycaster for hover/click
    const raycaster = new THREE.Raycaster()
    raycaster.params.Points = { threshold: 0.3 }
    const mouse = new THREE.Vector2()

    el.addEventListener('mousemove', (e) => {
      const rect = el.getBoundingClientRect()
      mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
      mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1

      // Find nearest point by proximity
      raycaster.setFromCamera(mouse, camera)
      const ray = raycaster.ray
      let nearest = -1
      let nearestDist = 0.5 // threshold

      for (let i = 0; i < positions.length; i++) {
        const dist = ray.distanceToPoint(positions[i])
        if (dist < nearestDist) {
          nearestDist = dist
          nearest = i
        }
      }

      hoveredNode = nearest >= 0 ? points[nearest].path : null
    })

    el.addEventListener('click', () => {
      if (hoveredNode) {
        const p = points.find(pt => pt.path === hoveredNode)
        if (p) {
          selectedPoint = { id: p.id, path: p.path, zone: p.zone, excerpt: p.excerpt }
        }
      } else {
        selectedPoint = null
      }
    })

    let image = 0
    function animate() {
      image = requestAnimationFrame(animate)
      time += 0.003

      const targetY = rotY + time * 0.2
      const targetX = rotX

      camera.position.x = 30 * Math.sin(targetY) * Math.cos(targetX)
      camera.position.y = 30 * Math.sin(targetX) + 5
      camera.position.z = 30 * Math.cos(targetY) * Math.cos(targetX)
      camera.lookAt(0, 0, 0)

      renderer.render(scene, camera)
    }

    animate()

    // Resize
    const resizeObserver = new ResizeObserver(() => {
      camera.aspect = el.clientWidth / el.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(el.clientWidth, el.clientHeight)
    })
    resizeObserver.observe(el)

    return () => {
      cancelAnimationFrame(image)
      resizeObserver.disconnect()
      renderer.dispose()
    }
  }

  onMount(() => {
    let quitte = false
    let nettoyer: (() => void) | undefined
    construire().then((n) => {
      // La vue a pu être quittée pendant le chargement : nettoyer tout de suite.
      if (quitte) n?.()
      else nettoyer = n
    })
    return () => {
      quitte = true
      nettoyer?.()
    }
  })
</script>

<div class="relative h-full">
  {#if loading}
    <div class="flex items-center justify-center h-full text-[var(--text-secondary)]">
      Chargement du cosmos...
    </div>
  {:else}
    <div bind:this={container} class="w-full h-full cursor-grab active:cursor-grabbing"></div>
  {/if}

  <!-- Hover tooltip -->
  {#if hoveredNode}
    <div
      class="absolute bg-[var(--bg-secondary)]/95 backdrop-blur
        border border-[var(--border)] rounded-lg px-3 py-1.5 text-xs pointer-events-none
        shadow-lg max-w-xs"
      style="left: {tooltipX + 16}px; top: {tooltipY - 12}px;"
    >
      {hoveredNode}
    </div>
  {/if}

  <!-- Selected point panel -->
  {#if selectedPoint}
    <div class="absolute bottom-6 right-6 bg-[var(--bg-secondary)]/95 backdrop-blur
      border border-[var(--border)] rounded-lg p-5 w-80 max-h-64 overflow-y-auto">
      <div class="flex items-center gap-3 mb-3">
        <div class="w-3 h-3 rounded-full" style="background: {getZoneColor(selectedPoint.zone)}"></div>
        <h3 class="font-semibold text-sm truncate">{selectedPoint.path}</h3>
      </div>
      <div class="text-xs text-[var(--text-secondary)] space-y-2">
        <div class="flex gap-2">
          <span class="text-[var(--accent)]">zone:</span> {selectedPoint.zone}
        </div>
        <div class="leading-relaxed opacity-80 whitespace-pre-wrap">{selectedPoint.excerpt.slice(0, 300)}</div>
      </div>
    </div>
  {/if}

  <!-- Legend -->
  <div class="absolute top-4 right-4 bg-[var(--bg-secondary)]/80 backdrop-blur
    border border-[var(--border)] rounded-lg p-4 text-xs">
    <div class="font-medium mb-2">Cosmos — Brain Map</div>
    <div class="space-y-1 text-[var(--text-secondary)]">
      <div>Clic : inspecter un chunk</div>
      <div>Glisser : orbiter</div>
      <div>{totalPoints} chunks</div>
    </div>
    <div class="mt-3 space-y-1">
      {#each Object.entries(ZONE_COLORS) as [zone, color]}
        <div class="flex items-center gap-2">
          <div class="w-2 h-2 rounded-full" style="background: {color}"></div>
          <span>{zone}</span>
        </div>
      {/each}
    </div>
  </div>
</div>
