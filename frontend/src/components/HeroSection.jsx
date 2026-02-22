import { motion } from "framer-motion";

export default function HeroSection() {
  return (
    <motion.section
      initial={{ opacity: 0, y: -20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.8, ease: "easeOut" }}
      className="text-center py-16 px-4"
    >
      <motion.h1
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.6, delay: 0.2 }}
        className="font-serif text-6xl md:text-8xl font-bold tracking-tight mb-4"
      >
        <span className="bg-gradient-to-r from-accent-gold via-white to-accent-teal bg-clip-text text-transparent">
          PLAYWRIGHT
        </span>
      </motion.h1>

      <motion.p
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.6, delay: 0.4 }}
        className="text-xl md:text-2xl text-white/60 font-light tracking-wide"
      >
        From script to screen in minutes
      </motion.p>

      <motion.div
        initial={{ scaleX: 0 }}
        animate={{ scaleX: 1 }}
        transition={{ duration: 0.8, delay: 0.6 }}
        className="w-32 h-0.5 bg-gradient-to-r from-accent-gold to-accent-teal mx-auto mt-8"
      />
    </motion.section>
  );
}
