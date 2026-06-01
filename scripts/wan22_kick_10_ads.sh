#!/usr/bin/env bash
# Submit 10 single-story 30-60s ads through the Wan22 pipeline.
# Each project is one coherent ad (5-8 connected beats), not a montage.
set -euo pipefail
BACKEND="${BACKEND_URL:-http://localhost:8002}"

post() {
    local title="$1" story="$2" dur="$3"
    local resp
    resp=$(curl -sf -X POST "$BACKEND/api/projects" -H "Content-Type: application/json" \
        -d "$(python3 -c "import json,sys; print(json.dumps({
            'title': '$title',
            'original_story_text': sys.stdin.read(),
            'total_target_duration_seconds': $dur,
            'pipeline_profile': 'wan22_text_only',
        }))" <<< "$story")")
    local id
    id=$(python3 -c "import json,sys; print(json.loads(sys.stdin.read())['id'])" <<< "$resp")
    echo "  $title -> $id"
}

echo "=== Submitting 10 single-story ads (Wan22) ==="

post "ad_01_chef_plating" "A 30-second ad. A male chef in his 40s, white jacket, short beard, plates a fine-dining dish in a stainless steel kitchen. Each 6-second scene: hands placing a microgreen, tweezers setting a sauce drop, brush of olive oil, plate spin reveal, wait staff lifting the dish toward the pass. Camera 4-8 feet, shallow depth-of-field, warm pendant lights, polished surfaces. No dialogue. Mood: precise, focused craft." 30

post "ad_02_running_woman" "A 30-second ad. A woman in her 30s, athletic build, dark hair in a low ponytail, technical running gear and trail shoes, completes a sunrise run on a coastal cliff trail. Each 6-second scene: trail shoes pushing off gravel, side-profile mid-stride along the cliff edge, breath visible against cool morning air, glance at the fitness watch on her wrist, final stride toward the sun cresting the ocean horizon. Camera 8-15 feet, smooth tracking, golden-hour backlight, cool tones warming to amber. No dialogue. Mood: determined, alive, grounded." 30

post "ad_03_coffee_cafe" "A 30-second ad. A young barista in her 20s, denim apron, expressive eyes, prepares a single pour-over coffee in a small artisan cafe. Each 6-second scene: paper filter being placed in a ceramic dripper, hot water spiraling in a slow concentric pour, steam rising from a thick-walled mug, the barista sliding the finished cup toward the wood counter, a customer's hands lifting it to take a first sip. Camera 3-6 feet, shallow depth-of-field, soft window light, warm wood tones. No dialogue. Mood: ritual, calm, sensory." 30

post "ad_04_electric_car" "A 30-second ad. A sleek midnight-blue electric sedan glides through a coastal landscape at dawn. Each 6-second scene: closeup of charging port releasing the cable with a soft snap, hand pressing the start button on a minimalist dashboard, the car gliding silently along an empty coastal road, side profile through a tunnel with light strobing across the body, the car cresting a hilltop overlooking the ocean. Camera 8-20 feet, polished cinematography, cool blues with soft horizon glow. No dialogue. Mood: refined, silent, modern." 30

post "ad_05_yoga_dawn" "A 30-second ad. A woman in her late 20s, lean build, hair tied back, in fitted athleisure, moves through a sunrise yoga sequence in a wood-floor studio with large windows. Each 6-second scene: bare feet finding the mat, downward dog with backlit sun streaming through the windows, slow transition to warrior pose, hands meeting at heart center in tree pose, final savasana with sunlight crossing her face. Camera 6-12 feet, side-tracking, golden-hour rim light, soft beige and amber palette. No dialogue. Mood: grounded, calm, centered." 30

post "ad_06_skincare_routine" "A 30-second ad. A woman in her 30s with bare skin and damp hair, in a marble bathroom with morning light, performs a five-step skincare routine. Each 6-second scene: pump of cleanser onto fingertips, gentle circular motion on cheekbones, drop of serum hitting the back of her hand, moisturizer being smoothed across her forehead and jawline, final reveal of glowing skin in the mirror with soft daylight halo. Camera 2-4 feet, macro to medium, very shallow depth-of-field, cool white tones. No dialogue. Mood: pure, fresh, luminous." 30

post "ad_07_headphones_studio" "A 30-second ad. A male music producer in his 30s, casual sweater, in a dimly-lit recording studio with warm console lights, listens through a pair of premium over-ear headphones. Each 6-second scene: closeup of leather earcup detail, headphones lifted toward his head, hands adjusting the cushioned fit, eyes closing as he listens, slow dolly pulling back to reveal the full studio with him at the center. Camera 2-6 feet, shallow depth-of-field, warm amber and deep teal lighting. No dialogue. Mood: immersive, refined, sonic." 30

post "ad_08_luxury_watch" "A 30-second ad. A man's wrist and hand, dark suit cuff, models a luxury mechanical watch in a softly-lit interior. Each 6-second scene: macro on the watch crown being wound, second hand sweeping across the dial face, light catching the polished bezel as the wrist turns, cuff sliding back to reveal the watch on the wrist, the wearer's hand reaching for a glass of whisky on a polished bar. Camera 1-3 feet, macro detail, very shallow depth-of-field, warm tungsten light on polished metal. No dialogue. Mood: refined, mechanical, timeless." 30

post "ad_09_running_shoes" "A 30-second ad. A male trail runner in his 20s, lean athletic build, in technical running kit, demonstrates a premium pair of trail-running shoes on a forest path at dawn. Each 6-second scene: closeup of laces being tightened on the shoe, foot striking damp earth with mud kicking up, side-profile mid-stride on a forest single-track, low-angle shot of the shoe sole gripping a rock, runner cresting a ridge with the sunrise behind him. Camera 3-15 feet, mix of macro and wide tracking, cool morning palette warming to gold. No dialogue. Mood: gritty, capable, free." 30

post "ad_10_perfume_bottle" "A 30-second ad. A woman in her 30s, elegant updo, silk slip dress, in a candlelit bedroom with soft drapes, applies a luxury perfume from a faceted glass bottle. Each 6-second scene: the perfume bottle resting on a marble vanity, her hand lifting the bottle and spraying a soft mist into the air, the mist drifting through the candlelight, perfume applied to the side of her neck, her reflection in the vanity mirror as she turns her face into the light. Camera 2-5 feet, shallow depth-of-field, warm tungsten and golden-amber, soft bokeh highlights. No dialogue. Mood: sensual, refined, romantic." 30

echo
echo "=== All 10 submitted ==="
echo "Status:  curl -s $BACKEND/api/projects | python3 -m json.tool | head -100"
echo "Celery:  tail -F /home/akash/PycharmProjects/video-app/backend/celery.log"
