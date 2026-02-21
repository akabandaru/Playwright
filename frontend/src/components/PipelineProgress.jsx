import { motion } from "framer-motion";

const STAGES = [
  { id: "analyzing", label: "Analyzing Script", icon: "🎬" },
  { id: "generating", label: "Visuals & Narration", icon: "🎨" },
  { id: "rendering", label: "Rendering Video", icon: "🎥" },
];

const STAGE_ORDER = [
  "analyzing",
  "generating",
  "rendering",
  "complete",
];

export default function PipelineProgress({ stage }) {
  const currentIndex = STAGE_ORDER.indexOf(stage);
  const progress =
    stage === "complete" ? 100 : (currentIndex / STAGES.length) * 100;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="w-full max-w-4xl mx-auto px-4 py-8"
    >
      <div className="glass-card p-6">
        <h3 className="text-white/80 font-medium mb-6 text-center">
          Pipeline Progress
        </h3>

        <div className="relative">
          {/* Background line */}
          <div className="absolute top-6 left-0 right-0 h-1 bg-white/10 rounded-full" />

          {/* Animated progress line */}
          <motion.div
            className="absolute top-6 left-0 h-1 bg-gradient-to-r from-accent-gold to-accent-teal rounded-full"
            initial={{ width: "0%" }}
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.5, ease: "easeOut" }}
          />

          {/* Stage nodes */}
          <div className="relative flex justify-between">
            {STAGES.map((s, index) => {
              const stageIndex = STAGE_ORDER.indexOf(s.id);
              const isActive = stage === s.id;
              const isComplete = currentIndex > stageIndex;

              return (
                <div key={s.id} className="flex flex-col items-center">
                  <motion.div
                    className={`w-12 h-12 rounded-full flex items-center justify-center text-xl z-10 transition-colors ${
                      isComplete
                        ? "bg-accent-teal text-background"
                        : isActive
                          ? "bg-accent-gold text-background"
                          : "bg-white/10 text-white/40"
                    }`}
                    animate={
                      isActive
                        ? {
                            scale: [1, 1.1, 1],
                            boxShadow: [
                              "0 0 0 0 rgba(245, 166, 35, 0)",
                              "0 0 0 10px rgba(245, 166, 35, 0.3)",
                              "0 0 0 0 rgba(245, 166, 35, 0)",
                            ],
                          }
                        : {}
                    }
                    transition={
                      isActive
                        ? {
                            duration: 1.5,
                            repeat: Infinity,
                            ease: "easeInOut",
                          }
                        : {}
                    }
                  >
                    {isComplete ? (
                      <svg
                        className="w-6 h-6"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={3}
                          d="M5 13l4 4L19 7"
                        />
                      </svg>
                    ) : (
                      s.icon
                    )}
                  </motion.div>

                  <span
                    className={`mt-3 text-xs font-medium text-center max-w-[80px] ${
                      isActive
                        ? "text-accent-gold"
                        : isComplete
                          ? "text-accent-teal"
                          : "text-white/40"
                    }`}
                  >
                    {s.label}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
