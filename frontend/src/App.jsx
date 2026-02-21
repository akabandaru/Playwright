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
      // Stage 1: Analyzing script
      setStage("analyzing");
      const analyzeResponse = await fetch(`${API_URL}/api/analyze`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ script }),
      });

      if (!analyzeResponse.ok) throw new Error("Failed to analyze script");
      const { beats: analyzedBeats } = await analyzeResponse.json();
      setBeats(analyzedBeats);

      // Stage 2: Generating visuals
      setStage("visuals");
      const visualsResponse = await fetch(`${API_URL}/api/generate-visuals`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ beats: analyzedBeats }),
      });

      if (!visualsResponse.ok) throw new Error("Failed to generate visuals");
      const { beats: beatsWithImages } = await visualsResponse.json();
      setBeats(beatsWithImages);
      setImages(beatsWithImages.map((b) => b.imageUrl));

      // Stage 3: Recording narration
      setStage("narration");
      const narrationResponse = await fetch(
        `${API_URL}/api/generate-narration`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ beats: beatsWithImages }),
        },
      );

      if (!narrationResponse.ok)
        throw new Error("Failed to generate narration");
      const { audioUrls, musicRecommendation: music } =
        await narrationResponse.json();
      setMusicRecommendation(music);

      // Stage 4: Rendering video
      setStage("rendering");
      const renderResponse = await fetch(`${API_URL}/api/render-video`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          beats: beatsWithImages,
          audioUrls,
        }),
      });

      if (!renderResponse.ok) throw new Error("Failed to render video");
      const { videoUrl: url } = await renderResponse.json();
      setVideoUrl(url);

      setStage("complete");
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
