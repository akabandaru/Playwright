import { motion } from "framer-motion";
import AudioPlayer from "./AudioPlayer";

const API_URL = "http://localhost:8000";

export default function StoryboardGrid({ beats }) {
  if (!beats || beats.length === 0) return null;

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
              ease: "easeOut",
            }}
            className="glass-card overflow-hidden group hover:border-accent-gold/30 transition-colors"
          >
            <div className="relative aspect-[16/10] overflow-hidden">
              {beat.imageUrl ? (
                <motion.img
                  key={beat.imageUrl}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ duration: 0.3 }}
                  src={
                    beat.imageUrl.startsWith("http")
                      ? beat.imageUrl
                      : `${API_URL}${beat.imageUrl}`
                  }
                  alt={`Beat ${index + 1}`}
                  className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-500"
                />
              ) : (
                <div className="w-full h-full bg-gradient-to-br from-white/5 to-white/10 flex flex-col items-center justify-center gap-3">
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{
                      duration: 2,
                      repeat: Infinity,
                      ease: "linear",
                    }}
                    className="w-8 h-8 border-2 border-accent-gold/30 border-t-accent-gold rounded-full"
                  />
                  <span className="text-white/40 text-xs">Generating...</span>
                </div>
              )}

              <div className="absolute top-3 left-3 w-8 h-8 rounded-full bg-black/60 backdrop-blur-sm flex items-center justify-center text-sm font-bold text-white">
                {index + 1}
              </div>

              {/* Badges */}
              <div className="absolute top-3 right-3 flex flex-col gap-2">
                {(beat.camera_angle || beat.cameraAngle) && (
                  <span className="badge-gold text-[10px]">
                    {beat.camera_angle || beat.cameraAngle}
                  </span>
                )}
                {beat.mood && (
                  <span className="badge-teal text-[10px]">{beat.mood}</span>
                )}
                {beat.lighting && (
                  <span className="badge-neutral text-[10px]">
                    {beat.lighting}
                  </span>
                )}
              </div>
            </div>

            {/* Visual description */}
            {(beat.visual_description || beat.visualDescription) && (
              <div className="p-4 border-t border-white/5">
                <p className="text-white/60 text-xs leading-relaxed">
                  {beat.visual_description || beat.visualDescription}
                </p>
              </div>
            )}

            {/* Narrator line */}
            {(beat.narrator_line || beat.narratorLine) && (
              <div className="p-4 border-t border-white/5">
                <p className="text-white/70 text-sm font-serif italic leading-relaxed">
                  "{beat.narrator_line || beat.narratorLine}"
                </p>
              </div>
            )}

            {/* Audio player */}
            {beat.audio_path && (
              <div className="p-4 border-t border-white/5">
                <AudioPlayer audioPath={beat.audio_path} />
              </div>
            )}
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}
