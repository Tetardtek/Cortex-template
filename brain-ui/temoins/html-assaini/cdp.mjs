// Témoin {@html} : ouvre la vue Documentation d'un build brain-ui et dit ce
// que la page piégée a pu faire. Chromium du système, port DevTools 18804.
const [,, url] = process.argv
const cible = (await (await fetch('http://127.0.0.1:18804/json/new?' + url, { method: 'PUT' })).json())
const ws = new WebSocket(cible.webSocketDebuggerUrl)
let id = 0
const attente = new Map()
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (attente.has(d.id)) { attente.get(d.id)(d); attente.delete(d.id) } }
await new Promise((r) => (ws.onopen = r))
const envoie = (method, params = {}) => new Promise((r) => { const i = ++id; attente.set(i, r); ws.send(JSON.stringify({ id: i, method, params })) })
const evalue = async (expr) => (await envoie('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result.result.value
const dort = (ms) => new Promise((r) => setTimeout(r, ms))
await dort(2500)
const clic = await evalue(`(() => { const b = [...document.querySelectorAll('button')].find(b => b.textContent.includes('Documentation')); if (!b) return false; b.click(); return true })()`)
await dort(2500)
const etat = await evalue(`(() => ({
  clic: ${clic},
  texte: !!document.querySelector('strong') && document.body.innerHTML.includes('<strong>normal</strong>'),
  pwned: document.body.getAttribute('data-pwned'),
  img_onerror: !!document.querySelector('[onerror]'),
  script: !!document.querySelector('main script'),
  lien_js: !!document.querySelector('a[href^="javascript:"]'),
}))()`)
console.log(JSON.stringify(etat))
ws.close()
