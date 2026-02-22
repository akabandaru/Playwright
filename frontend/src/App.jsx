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
  const [genrePreset, setGenrePreset] = useState("none");
  const [styleMode, setStyleMode] = useState("photoreal");
  const [beats, setBeats] = useState([]);
  const [images, setImages] = useState([]);
  const [videoUrl, setVideoUrl] = useState(null);
  const [figmaUrl, setFigmaUrl] = useState(null);
  const [stage, setStage] = useState(null);
  const [stageMessage, setStageMessage] = useState("");
  const [error, setError] = useState(null);
  const [musicRecommendation, setMusicRecommendation] = useState(null);
  const [selectedVoice, setSelectedVoice] = useState('auq43ws1oslv0tO4BDa7')

  const isGenerating = stage !== null && stage !== "complete";

  const runPipeline = useCallback(async () => {
    if (!script.trim()) return;

    setError(null);
    setBeats([]);
    setImages([]);
    setVideoUrl(null);
    setFigmaUrl(null);
    setMusicRecommendation(null);
    setStageMessage("");
    setStage("analyzing");

    try {
      const response = await fetch(`${API_URL}/api/generate-video`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ script, genre_preset: genrePreset, style_mode: styleMode, voice_id: selectedVoice }),
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
              if (data.message) {
                setStageMessage(data.message);
              }

              if (data.beats) {
                setBeats(data.beats);
                setImages(data.beats.map((b) => b.imageUrl).filter(Boolean));
              }

              // Handle individual beat updates (streaming images)
              if (data.beatUpdate) {
                const { index, beat } = data.beatUpdate;
                setBeats((prevBeats) => {
                  const newBeats = [...prevBeats];
                  newBeats[index] = { ...newBeats[index], ...beat };
                  return newBeats;
                });
                if (beat.imageUrl) {
                  setImages((prevImages) => {
                    const newImages = [...prevImages];
                    newImages[index] = beat.imageUrl;
                    return newImages;
                  });
                }
              }

              if (data.videoUrl) {
                setVideoUrl(`${API_URL}${data.videoUrl}`);
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
  }, [script, genrePreset, styleMode, selectedVoice]);

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
        selectedVoice={selectedVoice}
        setSelectedVoice={setSelectedVoice}
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
        {stage && stage !== "complete" && (
          <PipelineProgress stage={stage} message={stageMessage} />
        )}
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
