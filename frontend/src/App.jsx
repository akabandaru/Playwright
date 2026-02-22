import { useState, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import HeroSection from "./components/HeroSection";
import ScriptInput from "./components/ScriptInput";
import PipelineProgress from "./components/PipelineProgress";
import StoryboardGrid from "./components/StoryboardGrid";
import VideoPlayer from "./components/VideoPlayer";
import FigmaExportButton from "./components/FigmaExportButton";

const API_URL = "http://localhost:8000";

export default function App() {
  const [script, setScript] = useState("");
  const [genrePreset, setGenrePreset] = useState("none");
  const [styleMode, setStyleMode] = useState("photoreal");
  const [beats, setBeats] = useState([]);
  const [audioResults, setAudioResults] = useState([]);
  const [videoUrl, setVideoUrl] = useState(null);
  const [stage, setStage] = useState(null);
  const [stageMessage, setStageMessage] = useState("");
  const [error, setError] = useState(null);
  const [musicRecommendation, setMusicRecommendation] = useState(null);
  const [isRenderingVideo, setIsRenderingVideo] = useState(false);

  const isGenerating =
    stage !== null && stage !== "review" && stage !== "complete";

  const runPipeline = useCallback(async () => {
    if (!script.trim()) return;

    setError(null);
    setBeats([]);
    setAudioResults([]);
    setVideoUrl(null);
    setMusicRecommendation(null);
    setStageMessage("");
    setStage("analyzing");

    try {
      const response = await fetch(`${API_URL}/api/generate-video`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          script,
          genre_preset: genrePreset,
          style_mode: styleMode,
        }),
      });

      if (!response.ok) throw new Error("Failed to start pipeline");

      const reader = response.body.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));
              console.log("SSE data:", data);

              setStage(data.stage);
              if (data.message) setStageMessage(data.message);

              if (data.beats) {
                setBeats(data.beats);
              }

              if (data.beatUpdate) {
                const { index, beat } = data.beatUpdate;
                setBeats((prev) => {
                  const next = [...prev];
                  next[index] = { ...next[index], ...beat };
                  return next;
                });
              }

              if (data.audioResults) {
                setAudioResults(data.audioResults);
              }

              if (data.musicRecommendation) {
                setMusicRecommendation(data.musicRecommendation);
              }

              if (data.stage === "error") {
                setError(data.message);
                setStage(null);
                return;
              }
            } catch (parseError) {
              if (parseError.message !== "Unexpected end of JSON input") {
                console.error("Parse error:", parseError);
              }
            }
          }
        }
      }
    } catch (err) {
      console.error("Pipeline error:", err);
      setError(err.message || "An error occurred during generation");
      setStage(null);
    }
  }, [script, genrePreset, styleMode]);

  const handleBeatUpdated = useCallback((index, updatedBeat) => {
    setBeats((prev) => {
      const next = [...prev];
      next[index] = updatedBeat;
      return next;
    });
    if (updatedBeat.audio_path) {
      setAudioResults((prev) => {
        const next = [...prev];
        const existing = next.findIndex(
          (a) => a.beat_number === updatedBeat.beat_number
        );
        const entry = {
          beat_number: updatedBeat.beat_number,
          audio_path: updatedBeat.audio_path,
        };
        if (existing >= 0) next[existing] = entry;
        else next.push(entry);
        return next;
      });
    }
  }, []);

  const handleRenderVideo = useCallback(async () => {
    setIsRenderingVideo(true);
    setError(null);
    setStage("rendering");
    setStageMessage("Rendering video...");

    try {
      const res = await fetch(`${API_URL}/api/render-video`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ beats, audio_results: audioResults }),
      });

      if (!res.ok) throw new Error("Failed to render video");

      const data = await res.json();
      setVideoUrl(`${API_URL}${data.videoUrl}`);
      setStage("complete");
      setStageMessage("Video ready!");
    } catch (err) {
      console.error("Render video error:", err);
      setError(err.message || "Failed to render video");
      setStage("review");
    } finally {
      setIsRenderingVideo(false);
    }
  }, [beats, audioResults]);

  const inReview = stage === "review";

  return (
    <div className="min-h-screen bg-background">
      <HeroSection />

      <ScriptInput
        script={script}
        setScript={setScript}
        genrePreset={genrePreset}
        setGenrePreset={setGenrePreset}
        styleMode={styleMode}
        setStyleMode={setStyleMode}
        onGenerate={runPipeline}
        isGenerating={isGenerating}
      />

      <AnimatePresence>
        {error && (
          <div className="w-full max-w-4xl mx-auto px-4 py-4">
            <div className="glass-card p-4 border-red-500/30 bg-red-500/10">
              <p className="text-red-400 text-center">{error}</p>
            </div>
          </div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {stage &&
          stage !== "review" &&
          stage !== "complete" && (
            <PipelineProgress stage={stage} message={stageMessage} />
          )}
      </AnimatePresence>

      <AnimatePresence>
        {beats.length > 0 && (
          <StoryboardGrid
            beats={beats}
            styleMode={styleMode}
            genrePreset={genrePreset}
            editable={inReview}
            onBeatUpdated={handleBeatUpdated}
          />
        )}
      </AnimatePresence>

      {/* Generate Video + Figma buttons in review stage */}
      <AnimatePresence>
        {inReview && beats.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="w-full max-w-4xl mx-auto px-4 py-6 space-y-4"
          >
            <button
              onClick={handleRenderVideo}
              disabled={isRenderingVideo}
              className="flex items-center justify-center gap-3 w-full py-4 bg-accent-gold hover:bg-accent-gold/90 text-black font-semibold rounded-xl disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isRenderingVideo ? (
                <>
                  <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                  Rendering Video…
                </>
              ) : (
                <>
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
                    <path strokeLinecap="round" strokeLinejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Generate Video
                </>
              )}
            </button>

            <FigmaExportButton beats={beats} disabled={!beats.length} />
          </motion.div>
        )}
      </AnimatePresence>

      {/* After video is rendered */}
      <AnimatePresence>
        {videoUrl && (
          <VideoPlayer
            videoUrl={videoUrl}
            musicRecommendation={musicRecommendation}
          />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {stage === "complete" && beats.length > 0 && (
          <FigmaExportButton beats={beats} disabled={!beats.length} />
        )}
      </AnimatePresence>
    </div>
  );
}
