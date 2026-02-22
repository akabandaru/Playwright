import { useState, useRef } from "react";

const API_URL = "http://localhost:8000";

export default function AudioPlayer({ audioPath }) {
  const [isPlaying, setIsPlaying] = useState(false);
  const audioRef = useRef(null);

  if (!audioPath) return null;

  const audioUrl = audioPath.startsWith("http")
    ? audioPath
    : `${API_URL}/api/audio/${encodeURIComponent(audioPath)}`;

  const togglePlay = () => {
    if (audioRef.current) {
      if (isPlaying) {
        audioRef.current.pause();
      } else {
        audioRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  };

  const handleEnded = () => {
    setIsPlaying(false);
  };

  return (
    <div className="flex items-center gap-2 p-3 bg-white/5 rounded-lg">
      <button
        onClick={togglePlay}
        className="w-8 h-8 flex items-center justify-center bg-accent-gold/20 hover:bg-accent-gold/40 rounded-full transition-colors"
      >
        {isPlaying ? (
          <svg
            className="w-4 h-4 text-accent-gold"
            fill="currentColor"
            viewBox="0 0 24 24"
          >
            <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
          </svg>
        ) : (
          <svg
            className="w-4 h-4 text-accent-gold"
            fill="currentColor"
            viewBox="0 0 24 24"
          >
            <path d="M8 5v14l11-7z" />
          </svg>
        )}
      </button>
      <span className="text-white/60 text-xs">Listen to narration</span>
      <audio
        ref={audioRef}
        src={audioUrl}
        onEnded={handleEnded}
        preload="none"
      />
    </div>
  );
}
