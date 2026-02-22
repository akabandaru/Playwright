import { motion } from 'framer-motion'

const EXAMPLE_SCENE = `INT. ABANDONED WAREHOUSE - NIGHT

Rain hammers against broken windows. DETECTIVE MAYA CHEN (40s) steps through the doorway, flashlight cutting through darkness.

MAYA
(whispered)
I know you're here, Marcus.

A SHADOW shifts behind rusted machinery. MARCUS VALE (50s) emerges, hands raised, face half-lit by moonlight.

MARCUS
You shouldn't have come alone.

Maya's hand moves to her holster. Thunder RUMBLES outside.

MAYA
I never do.

RED AND BLUE LIGHTS flood through the windows. Marcus smiles—but it doesn't reach his eyes.`

const GENRE_PRESETS = [
  { value: 'none', label: 'None (Balanced)' },
  { value: 'noir', label: 'Noir' },
  { value: 'thriller', label: 'Thriller' },
  { value: 'romcom', label: 'Rom-Com' },
]

const STYLE_MODES = [
  { value: 'photoreal', label: 'Photoreal' },
  { value: 'anime', label: 'Anime' },
]

export default function ScriptInput({
  script,
  setScript,
  genrePreset,
  setGenrePreset,
  styleMode,
  setStyleMode,
  onGenerate,
  isGenerating,
}) {
  const handleLoadExample = () => {
    setScript(EXAMPLE_SCENE)
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, delay: 0.3 }}
      className="w-full max-w-4xl mx-auto px-4"
    >
      <div className="glass-card p-6">
        <div className="flex items-center justify-between mb-4">
          <label className="text-white/80 font-medium">Your Script</label>
          <button
            onClick={handleLoadExample}
            className="text-sm text-accent-teal hover:text-accent-teal/80 transition-colors"
          >
            Load Example Scene
          </button>
        </div>
        
        <textarea
          value={script}
          onChange={(e) => setScript(e.target.value)}
          placeholder="Paste your screenplay or scene here..."
          className="w-full min-h-50 bg-black/40 border border-white/10 rounded-xl p-4 text-white placeholder-white/30 focus:outline-none focus:border-accent-gold/50 focus:ring-1 focus:ring-accent-gold/30 resize-y font-mono text-sm leading-relaxed transition-all"
        />

        <div className="mt-4 grid gap-3 rounded-xl border border-white/10 bg-black/30 p-3 md:grid-cols-2">
          <div className="flex items-center justify-between gap-3">
            <label htmlFor="genre-preset" className="text-sm text-white/70">Genre Preset</label>
            <select
              id="genre-preset"
              value={genrePreset}
              onChange={(e) => setGenrePreset(e.target.value)}
              className="bg-black/50 border border-white/15 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-accent-gold/50"
            >
              {GENRE_PRESETS.map((preset) => (
                <option key={preset.value} value={preset.value}>
                  {preset.label}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center justify-between gap-3">
            <label htmlFor="style-mode" className="text-sm text-white/70">Style</label>
            <select
              id="style-mode"
              value={styleMode}
              onChange={(e) => setStyleMode(e.target.value)}
              className="bg-black/50 border border-white/15 rounded-lg px-3 py-1.5 text-sm text-white focus:outline-none focus:border-accent-gold/50"
            >
              {STYLE_MODES.map((mode) => (
                <option key={mode.value} value={mode.value}>
                  {mode.label}
                </option>
              ))}
            </select>
          </div>
        </div>

        <motion.button
          onClick={onGenerate}
          disabled={isGenerating || !script.trim()}
          whileHover={{ scale: 1.02 }}
          whileTap={{ scale: 0.98 }}
          className="mt-4 w-full py-4 bg-linear-to-r from-accent-gold to-accent-teal text-background font-semibold rounded-xl disabled:opacity-50 disabled:cursor-not-allowed transition-all hover:shadow-lg hover:shadow-accent-gold/20"
        >
          {isGenerating ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
              </svg>
              Generating...
            </span>
          ) : (
            'Generate Storyboard & Video'
          )}
        </motion.button>
      </div>
    </motion.div>
  )
}
