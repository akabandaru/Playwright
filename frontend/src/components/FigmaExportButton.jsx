import { useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'

const API_URL = 'http://localhost:8000'

// ── Figma wordmark logo ───────────────────────────────────────────────────────
const FigmaLogo = ({ size = 20 }) => (
  <svg width={size} height={size * (57 / 38)} viewBox="0 0 38 57" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M19 28.5C19 23.2533 23.2533 19 28.5 19C33.7467 19 38 23.2533 38 28.5C38 33.7467 33.7467 38 28.5 38C23.2533 38 19 33.7467 19 28.5Z" fill="#1ABCFE"/>
    <path d="M0 47.5C0 42.2533 4.25329 38 9.5 38H19V47.5C19 52.7467 14.7467 57 9.5 57C4.25329 57 0 52.7467 0 47.5Z" fill="#0ACF83"/>
    <path d="M19 0V19H28.5C33.7467 19 38 14.7467 38 9.5C38 4.25329 33.7467 0 28.5 0H19Z" fill="#FF7262"/>
    <path d="M0 9.5C0 14.7467 4.25329 19 9.5 19H19V0H9.5C4.25329 0 0 4.25329 0 9.5Z" fill="#F24E1E"/>
    <path d="M0 28.5C0 33.7467 4.25329 38 9.5 38H19V19H9.5C4.25329 19 0 23.2533 0 28.5Z" fill="#A259FF"/>
  </svg>
)

const CheckIcon = () => (
  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
  </svg>
)

const CopyIcon = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
    <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1"/>
  </svg>
)

const ExternalLinkIcon = () => (
  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
  </svg>
)

// ── Build the figma:// deep link URL ─────────────────────────────────────────
function buildDeepLink(storyboardId, apiUrl) {
  // Figma deep link format:
  //   figma://run?pluginId=<id>&pluginData=<json>
  // When the user clicks this in a browser, macOS opens Figma desktop and
  // launches the plugin with the pluginData available as figma.pluginData.
  const pluginData = JSON.stringify({ storyboard_id: storyboardId, api_url: apiUrl })
  return `figma://run?pluginId=playwright-storyboard-exporter&pluginData=${encodeURIComponent(pluginData)}`
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function FigmaExportButton({ beats, disabled }) {
  const [state, setState] = useState('idle')   // 'idle' | 'loading' | 'ready'
  const [storyboardId, setStoryboardId] = useState(null)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)

  const handleExport = async () => {
    setState('loading')
    setError(null)

    try {
      const response = await fetch(`${API_URL}/api/export-figma`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ beats }),
      })

      if (!response.ok) throw new Error('Export failed')

      const data = await response.json()
      setStoryboardId(data.storyboard_id)
      setState('ready')
    } catch (err) {
      setError('Failed to export. Is the backend running?')
      setState('idle')
      console.error(err)
    }
  }

  const handleCopyId = async () => {
    if (!storyboardId) return
    try {
      await navigator.clipboard.writeText(storyboardId)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (_) {
      // Fallback for non-secure contexts
      const el = document.createElement('textarea')
      el.value = storyboardId
      document.body.appendChild(el)
      el.select()
      document.execCommand('copy')
      document.body.removeChild(el)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const deepLink = storyboardId ? buildDeepLink(storyboardId, API_URL) : '#'

  return (
    <div className="w-full max-w-4xl mx-auto px-4 py-4 space-y-3">
      <AnimatePresence mode="wait">

        {/* ── Idle: Export button ─────────────────────────────────────────── */}
        {state === 'idle' && (
          <motion.button
            key="idle"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            onClick={handleExport}
            disabled={disabled}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="flex items-center justify-center gap-3 w-full py-4 bg-[#7B61FF] hover:bg-[#6B51EF] text-white font-semibold rounded-xl disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <FigmaLogo />
            Export Storyboard to Figma
          </motion.button>
        )}

        {/* ── Loading ─────────────────────────────────────────────────────── */}
        {state === 'loading' && (
          <motion.div
            key="loading"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="flex items-center justify-center gap-3 w-full py-4 bg-[#7B61FF]/60 text-white font-semibold rounded-xl cursor-wait"
          >
            <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
            Preparing storyboard…
          </motion.div>
        )}

        {/* ── Ready: deep link + copy fallback ────────────────────────────── */}
        {state === 'ready' && (
          <motion.div
            key="ready"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="space-y-3"
          >
            {/* Primary CTA — opens Figma desktop and launches the plugin */}
            <a
              href={deepLink}
              className="flex items-center justify-center gap-3 w-full py-4 bg-[#7B61FF] hover:bg-[#6B51EF] text-white font-semibold rounded-xl transition-colors"
            >
              <FigmaLogo />
              Open in Figma Plugin
              <ExternalLinkIcon />
            </a>

            {/* Info row */}
            <p className="text-center text-xs text-white/40 leading-relaxed">
              Opens Figma desktop and launches the PLAYWRIGHT plugin automatically.
              <br />
              The plugin will import your storyboard with one click.
            </p>

            {/* Fallback — copy the storyboard ID for manual paste */}
            <div className="flex items-center gap-2 p-3 rounded-xl bg-white/5 border border-white/10">
              <span className="text-xs text-white/40 flex-shrink-0">Storyboard ID</span>
              <span className="flex-1 text-xs text-white/70 font-mono truncate">{storyboardId}</span>
              <button
                onClick={handleCopyId}
                title="Copy storyboard ID"
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-white/70 text-xs font-medium transition-colors flex-shrink-0"
              >
                {copied ? <CheckIcon /> : <CopyIcon />}
                {copied ? 'Copied!' : 'Copy'}
              </button>
            </div>

            {/* Re-export link */}
            <button
              onClick={() => { setState('idle'); setStoryboardId(null) }}
              className="w-full text-xs text-white/30 hover:text-white/50 transition-colors py-1"
            >
              Re-export with new images
            </button>
          </motion.div>
        )}

      </AnimatePresence>

      {/* Error */}
      <AnimatePresence>
        {error && (
          <motion.p
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="text-red-400 text-sm text-center"
          >
            {error}
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  )
}
