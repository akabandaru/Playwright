import { motion } from 'framer-motion'

export default function VideoPlayer({ videoUrl, musicRecommendation }) {
  if (!videoUrl) return null

  const handleDownload = () => {
    const link = document.createElement('a')
    link.href = videoUrl
    link.download = 'playwright-video.mp4'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 40 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.6, ease: 'easeOut' }}
      className="w-full max-w-4xl mx-auto px-4 py-8"
    >
      <div className="glass-card overflow-hidden">
        <div className="p-4 border-b border-white/10">
          <h2 className="text-xl font-serif font-bold text-white flex items-center gap-2">
            <span className="text-accent-gold">▶</span>
            Generated Video
          </h2>
          {musicRecommendation && (
            <p className="text-white/50 text-sm mt-1">
              🎵 Recommended: <span className="text-accent-teal">{musicRecommendation}</span>
            </p>
          )}
        </div>
        
        <div className="relative aspect-video bg-black">
          <video
            src={videoUrl}
            controls
            autoPlay
            loop
            className="w-full h-full"
          >
            Your browser does not support the video tag.
          </video>
        </div>
        
        <div className="p-4 flex justify-end">
          <motion.button
            onClick={handleDownload}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="flex items-center gap-2 px-6 py-3 bg-gradient-to-r from-accent-gold to-accent-teal text-background font-semibold rounded-xl hover:shadow-lg hover:shadow-accent-gold/20 transition-shadow"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            Download MP4
          </motion.button>
        </div>
      </div>
    </motion.div>
  )
}
