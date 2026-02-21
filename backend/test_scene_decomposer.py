"""
Quick test for scene_decomposer.  Run from the backend/ folder:

    source venv/bin/activate
    python test_scene_decomposer.py
"""

import asyncio
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env before any service imports so GEMINI_API_KEY is available
load_dotenv(Path(__file__).parent / ".env")

sys.path.insert(0, str(Path(__file__).parent))
from services.scene_decomposer import decompose_scene
from services.elevenlabs_service import generate_voices_and_sfx
from services.scene_decomposer import close_client

# TEST_SCENE = """
# BURNING. Massive flames. A dark shape emerges- The BAT
# SYMBOL. Growing. Filling the screen with BLACKNESS.
# CUT TO:
# DAYLIGHT. Moving over the towers of downtown Gotham...
# Closing in on an office building... On a large window...
# Which SHATTERS to revealINT. OFFICE, HIGH RISE -- DAY
# A man in a CLOWN MASK holding a SMOKING SILENCED PISTOL
# ejects a shell casing. This is DOPEY. He turns to a second
# man, HAPPY, also in clown mask, who steps forward with a
# CABLE LAUNCHER, aims at a lower roof across the street and
# FIRES a cable across. Dopey secures the line to an I-beam
# line- CLAMP on- sends a KIT BAG out then steps OUT the
# window...
# EXT. HIGH-RISE -- DAY
# ...into space. The men SLIDE across the DIZZYING DROP...
# landing on the lower roof across the street.
# EXT. DOWNTOWN GOTHAM -- DAY
# A MAN on the corner, back to us, holding a CLOWN MASK. An
# SUV pulls up. The man gets in, puts on his mask. Inside the
# car- two other men wearing CLOWN MASKS.
# GRUMPY
# Three of a kind. Let's do this.
# One of the Clowns looks up from loading his automatic weapon.
# CHUCKLES
# That's it? Three guys?
# GRUMPY
# There's two on the roof. Every guy
# is an extra share. Five shares is
# plenty.
# CHUCKLES
# Six shares. Don't forget the guy who
# planned the job.
# GRUMPY
# Yeah? He thinks he can sit it out
# and still take a slice then I get why
# they call him the Joker.
# Grumpy cocks his weapon. Bozo pulls the car over in front of
# the GOTHAM FIRST NATIONAL BANK.
# """

TEST_SCENE = """
A quiet, nearly empty cafe. Rain lashes against the windows.
ARTHUR (60s, wearing a worn tweed jacket) sits at a corner table. He is frantically writing in a notebook, muttering to himself.
Opposite him sits a completely full, untouched cup of black coffee.
He stops writing. Looks at the door.
"""

async def main():
    try:
        print("Testing scene_decomposer.decompose_scene()...")
        print(f"Scene: {TEST_SCENE.strip()[:80]}...\n")

        result = await decompose_scene(TEST_SCENE)

        print(f"run_id:                {result['run_id']}")
        print(f"beats_extracted:       {result['beats_extracted']}")
        print(f"inference_time:        {result['inference_time_seconds']}s")
        print(f"tokens_used:           {result['tokens_used']}")
        print()

        for beat in result["beats"]:
            print(f"  Beat {beat.get('beat_number')} | {beat.get('camera_angle')} | "
                f"{beat.get('mood')} | {beat.get('lighting')}")
            print(f"    {beat.get('visual_description', '')[:80]}")
            print(f"    Narrator: \"{beat.get('narrator_line', '')[:70]}\"")
            print()

        print("Full JSON output:")
        print(json.dumps(result["beats"], indent=2))

        audio_results = await generate_voices_and_sfx(result['beats'])
        print("Audio results:", audio_results)
    finally:
        await close_client()

asyncio.run(main())
