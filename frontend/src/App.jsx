import { useState, useCallback } from "react";
import { AnimatePresence } from "framer-motion";
import HeroSection from "./components/HeroSection";
import ScriptInput from "./components/ScriptInput";
import PipelineProgress from "./components/PipelineProgress";
import StoryboardGrid from "./components/StoryboardGrid";
import VideoPlayer from "./components/VideoPlayer";
import FigmaExportButton from "./components/FigmaExportButton";

const API_URL = "http://localhost:8000";

export default function App() {
  const [script, setScript] = useState("");
  const [beats, setBeats] = useState([]);
  const [images, setImages] = useState([]);
  const [videoUrl, setVideoUrl] = useState(null);
  const [figmaUrl, setFigmaUrl] = useState(null);
  const [stage, setStage] = useState(null);
  const [error, setError] = useState(null);
  const [musicRecommendation, setMusicRecommendation] = useState(null);

  const isGenerating = stage !== null && stage !== "complete";

  const runPipeline = useCallback(async () => {
    if (!script.trim()) return;

    setError(null);
    setBeats([]);
    setImages([]);
    setVideoUrl(null);
    setFigmaUrl(null);
    setMusicRecommendation(null);

    try {
      const response = await fetch(`${API_URL}/api/generate-video`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ script }),
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
              
              setStage(data.stage);

              if (data.beats) {
                setBeats(data.beats);
                setImages(data.beats.map((b) => b.imageUrl).filter(Boolean));
              }

              if (data.videoUrl) {
                setVideoUrl(data.videoUrl);
              }

              if (data.musicRecommendation) {
                setMusicRecommendation(data.musicRecommendation);
              }

              if (data.stage === "error") {
                throw new Error(data.message);
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
  }, [script]);

  return (
    <div className="min-h-screen bg-background">
      <HeroSection />

      <ScriptInput
        script={script}
        setScript={setScript}
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
        {stage && stage !== "complete" && <PipelineProgress stage={stage} />}
      </AnimatePresence>

      <AnimatePresence>
        {beats.length > 0 && <StoryboardGrid beats={beats} />}
      </AnimatePresence>

      <AnimatePresence>
        {beats.length > 0 && stage === "complete" && (
          <FigmaExportButton beats={beats} disabled={!beats.length} />
        )}
      </AnimatePresence>

      <AnimatePresence>
        {videoUrl && (
          <VideoPlayer
            videoUrl={videoUrl}
            musicRecommendation={musicRecommendation}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
