import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import AudioPlayer from "./AudioPlayer";

const API_URL = "http://localhost:8000";

const Spinner = ({ className = "w-3.5 h-3.5" }) => (
  <svg className={`animate-spin ${className}`} viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
  </svg>
);

export default function BeatEditModal({
  beat,
  index,
  styleMode,
  genrePreset,
  onClose,
  onBeatUpdated,
}) {
  const [isRegeneratingImage, setIsRegeneratingImage] = useState(false);
  const [isRegeneratingNarrator, setIsRegeneratingNarrator] = useState(false);
  const [isReimagining, setIsReimagining] = useState(false);
  const [narratorLine, setNarratorLine] = useState(
    beat.narrator_line || beat.narratorLine || ""
  );
  const [feedback, setFeedback] = useState("");
  const [regenImage, setRegenImage] = useState(true);
  const [regenNarrator, setRegenNarrator] = useState(true);

  const handleReimagine = async () => {
    if (!feedback.trim()) return;
    setIsReimagining(true);
    if (regenImage) setIsRegeneratingImage(true);
    if (regenNarrator) setIsRegeneratingNarrator(true);

    try {
      const res = await fetch(`${API_URL}/api/reimagine-beat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          beat,
          feedback,
          genre_preset: genrePreset,
          style_mode: styleMode,
          regenerate_image: regenImage,
          regenerate_narrator: regenNarrator,
        }),
      });
      if (!res.ok) throw new Error("Failed to reimagine beat");
      const data = await res.json();

      const revised = {
        ...beat,
        ...data.beat,
        ...(data.imageUrl && { imageUrl: data.imageUrl, image_url: data.imageUrl }),
        ...(data.audio_path && { audio_path: data.audio_path }),
        ...(data.audio_url && { audio_url: data.audio_url }),
      };

      onBeatUpdated(index, revised);
      setNarratorLine(revised.narrator_line || "");
      setFeedback("");
    } catch (err) {
      console.error("Reimagine beat error:", err);
    } finally {
      setIsReimagining(false);
      setIsRegeneratingImage(false);
      setIsRegeneratingNarrator(false);
    }
  };

  const handleRegenerateImage = async () => {
    setIsRegeneratingImage(true);
    try {
      const res = await fetch(`${API_URL}/api/regenerate-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ beat, style_mode: styleMode }),
      });
      if (!res.ok) throw new Error("Failed to regenerate image");
      const data = await res.json();
      onBeatUpdated(index, {
        ...beat,
        imageUrl: data.imageUrl,
        image_url: data.imageUrl,
      });
    } catch (err) {
      console.error("Regenerate image error:", err);
    } finally {
      setIsRegeneratingImage(false);
    }
  };

  const handleRegenerateNarrator = async () => {
    setIsRegeneratingNarrator(true);
    try {
      const updatedBeat = { ...beat, narrator_line: narratorLine };
      const res = await fetch(`${API_URL}/api/regenerate-narrator`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ beat: updatedBeat }),
      });
      if (!res.ok) throw new Error("Failed to regenerate narrator");
      const data = await res.json();
      onBeatUpdated(index, {
        ...updatedBeat,
        audio_path: data.audio_path,
        audio_url: data.audio_url,
      });
    } catch (err) {
      console.error("Regenerate narrator error:", err);
    } finally {
      setIsRegeneratingNarrator(false);
    }
  };

  const imageUrl = beat.imageUrl || beat.image_url;
  const fullImageUrl =
    imageUrl && !imageUrl.startsWith("http")
      ? `${API_URL}${imageUrl}`
      : imageUrl;

  const isBusy = isReimagining || isRegeneratingImage || isRegeneratingNarrator;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.95, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.95, y: 20 }}
        transition={{ duration: 0.2 }}
        className="glass-card w-full max-w-2xl max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-white/10">
          <h3 className="text-lg font-serif font-bold text-white">
            Edit Beat {index + 1}
          </h3>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-full bg-white/10 hover:bg-white/20 text-white/60 hover:text-white transition-colors"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="p-5 space-y-5">
          {/* Reimagine section — user feedback */}
          <div className="space-y-2 p-4 rounded-xl bg-purple-500/5 border border-purple-500/20">
            <span className="text-sm font-medium text-purple-300">
              Reimagine this beat
            </span>
            <p className="text-white/40 text-xs">
              Describe what to change — Gemini will rewrite the beat while keeping the same structure.
            </p>
            <textarea
              value={feedback}
              onChange={(e) => setFeedback(e.target.value)}
              placeholder='e.g. "Make the scene darker and more tense" or "Thanos has 6 infinity stones not 8"'
              rows={2}
              disabled={isBusy}
              className="w-full p-3 text-sm text-white/80 bg-white/5 border border-white/10 rounded-lg focus:outline-none focus:border-purple-400/40 resize-none placeholder:text-white/20"
            />
            <div className="flex items-center gap-5 pt-1">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={regenImage}
                  onChange={(e) => setRegenImage(e.target.checked)}
                  disabled={isBusy}
                  className="w-3.5 h-3.5 rounded accent-purple-400"
                />
                <span className="text-xs text-white/50">Regenerate Image</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={regenNarrator}
                  onChange={(e) => setRegenNarrator(e.target.checked)}
                  disabled={isBusy}
                  className="w-3.5 h-3.5 rounded accent-purple-400"
                />
                <span className="text-xs text-white/50">Remake Narration</span>
              </label>
            </div>
            <button
              onClick={handleReimagine}
              disabled={isBusy || !feedback.trim()}
              className="flex items-center gap-2 px-4 py-2 text-xs font-medium rounded-lg bg-purple-500/20 hover:bg-purple-500/30 text-purple-300 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isReimagining ? (
                <>
                  <Spinner />
                  Reimagining…
                </>
              ) : (
                <>
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 3v4M3 5h4M6 17v4m-2-2h4m5-16l2.286 6.857L21 12l-5.714 2.143L13 21l-2.286-6.857L5 12l5.714-2.143L13 3z" />
                  </svg>
                  Reimagine Beat
                </>
              )}
            </button>
          </div>

          {/* Image section */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-white/70">Image</span>
              <button
                onClick={handleRegenerateImage}
                disabled={isBusy}
                className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg bg-accent-gold/20 hover:bg-accent-gold/30 text-accent-gold disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isRegeneratingImage ? (
                  <>
                    <Spinner />
                    Regenerating…
                  </>
                ) : (
                  <>
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    Regenerate Image
                  </>
                )}
              </button>
            </div>
            {fullImageUrl && (
              <div className="relative aspect-video rounded-lg overflow-hidden">
                <AnimatePresence mode="wait">
                  <motion.img
                    key={fullImageUrl}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    src={fullImageUrl}
                    alt={`Beat ${index + 1}`}
                    className="w-full h-full object-cover"
                  />
                </AnimatePresence>
                {isRegeneratingImage && (
                  <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
                    <motion.div
                      animate={{ rotate: 360 }}
                      transition={{ duration: 1.5, repeat: Infinity, ease: "linear" }}
                      className="w-10 h-10 border-2 border-accent-gold/30 border-t-accent-gold rounded-full"
                    />
                  </div>
                )}
              </div>
            )}
            <div className="flex flex-wrap gap-2">
              {beat.camera_angle && (
                <span className="badge-gold text-[10px]">{beat.camera_angle}</span>
              )}
              {beat.mood && (
                <span className="badge-teal text-[10px]">{beat.mood}</span>
              )}
              {beat.lighting && (
                <span className="badge-neutral text-[10px]">{beat.lighting}</span>
              )}
            </div>
          </div>

          {/* Visual description */}
          {beat.visual_description && (
            <div className="space-y-1">
              <span className="text-sm font-medium text-white/70">Visual Description</span>
              <p className="text-white/50 text-xs leading-relaxed p-3 bg-white/5 rounded-lg">
                {beat.visual_description}
              </p>
            </div>
          )}

          {/* Narrator line (editable) */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-white/70">Narrator Line</span>
              <button
                onClick={handleRegenerateNarrator}
                disabled={isBusy || !narratorLine.trim()}
                className="flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg bg-teal-500/20 hover:bg-teal-500/30 text-teal-400 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isRegeneratingNarrator ? (
                  <>
                    <Spinner />
                    Regenerating…
                  </>
                ) : (
                  <>
                    <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                    </svg>
                    Remake Narration
                  </>
                )}
              </button>
            </div>
            <textarea
              value={narratorLine}
              onChange={(e) => setNarratorLine(e.target.value)}
              rows={3}
              disabled={isBusy}
              className="w-full p-3 text-sm text-white/80 bg-white/5 border border-white/10 rounded-lg focus:outline-none focus:border-accent-gold/40 resize-none font-serif italic"
            />
          </div>

          {/* Audio preview */}
          {(beat.audio_url || beat.audio_path) && (
            <div className="space-y-1">
              <span className="text-sm font-medium text-white/70">Audio Preview</span>
              <AudioPlayer
                key={beat.audio_url || beat.audio_path}
                audioPath={beat.audio_url || beat.audio_path}
              />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-5 border-t border-white/10 flex justify-end">
          <button
            onClick={onClose}
            className="px-5 py-2 text-sm font-medium rounded-lg bg-white/10 hover:bg-white/20 text-white transition-colors"
          >
            Done
          </button>
        </div>
      </motion.div>
    </motion.div>
  );
}
