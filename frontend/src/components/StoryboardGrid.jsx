import { motion } from 'framer-motion'

export default function StoryboardGrid({ beats }) {
  if (!beats || beats.length === 0) return null

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="w-full max-w-6xl mx-auto px-4 py-8"
    >
      <h2 className="text-2xl font-serif font-bold text-white mb-6 text-center">
        Storyboard
      </h2>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {beats.map((beat, index) => (
          <motion.div
            key={beat.id || index}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.5,
              delay: index * 0.1,
              ease: 'easeOut',
            }}
            className="glass-card overflow-hidden group hover:border-accent-gold/30 transition-colors"
          >
            {/* Image container */}
            <div className="relative aspect-[16/10] overflow-hidden">
              {beat.imageUrl ? (
                <img
                  src={beat.imageUrl}
                  alt={`Beat ${index + 1}`}
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                />
              ) : (
                <div className="w-full h-full bg-gradient-to-br from-white/5 to-white/10 flex items-center justify-center">
                  <svg className="w-12 h-12 text-white/20" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                </div>
              )}
              
              {/* Beat number overlay */}
              <div className="absolute top-3 left-3 w-8 h-8 rounded-full bg-black/60 backdrop-blur-sm flex items-center justify-center text-sm font-bold text-white">
                {index + 1}
              </div>
              
              {/* Badges */}
              <div className="absolute top-3 right-3 flex flex-col gap-2">
                {beat.cameraAngle && (
                  <span className="badge-gold text-[10px]">
                    {beat.cameraAngle}
                  </span>
                )}
                {beat.mood && (
                  <span className="badge-teal text-[10px]">
                    {beat.mood}
                  </span>
                )}
                {beat.lighting && (
                  <span className="badge-neutral text-[10px]">
                    {beat.lighting}
                  </span>
                )}
              </div>
            </div>
            
            {/* Narrator line */}
            {beat.narratorLine && (
              <div className="p-4 border-t border-white/5">
                <p className="text-white/70 text-sm font-serif italic leading-relaxed">
                  "{beat.narratorLine}"
                </p>
              </div>
            )}
          </motion.div>
        ))}
      </div>
    </motion.div>
  )
}
