"""One-off: rewrite ep#0's 36 LTX prompts as ≤225-char tight versions
and re-enqueue scenes for render. No deletes."""
from __future__ import annotations
import asyncio
import sys
from sqlalchemy import select
from sqlalchemy.orm import selectinload
sys.path.insert(0, "/home/akash/PycharmProjects/video-app/backend")
from app.database import async_session_factory
from app.models.project import Project, ProjectStatus
from app.models.episode import Episode
from app.models.scene import Scene, SceneStatus
from app.models.scene_prompt import ScenePrompt
from app.models.asset import Asset, AssetType
from app.models.render_job import RenderJob, JobType, JobStatus

PID = "35df851c-506e-4b93-9f71-e0aad8fb5c6b"

PROMPTS = {
    0: "Wide. Ghibli watercolor. Tamil man Jaggi (25, black hair, mustache, cream shirt) bounds out of an ochre doorway, grinning up at the bright South Indian sky. Slow joyful motion.",
    1: "Wide. Ghibli watercolor. Jaggi (Tamil 25, black hair, mustache, cream shirt) strides down a sunlit tamarind-lined lane, hands loose, grinning. Slow joyful motion.",
    2: "Close. Ghibli watercolor. Jaggi's hand (Tamil 25, mustache) slaps the dusty motorcycle fuel tank with affection, delighted smile in frame. Warm morning light. Slow.",
    3: "Wide. Ghibli watercolor. Jaggi (Tamil 25, black hair, mustache, cream shirt) astride his motorcycle, head turned toward distant Chamundi Hill with playful delight. Slow.",
    4: "Medium. Ghibli watercolor. Jaggi (Tamil 25, mustache, cream shirt) strides down the central aisle of a red brick poultry shed, ledger under arm, easy grin. Slow.",
    5: "Medium. Ghibli watercolor. Jaggi (Tamil 25, mustache) crouches by a feed trough, flips ledger page, springs back up, joyful unhurried energy. Slow.",
    6: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache, cream shirt) walks the edge of a bamboo-scaffolded second floor, sure-footed and grinning at the town below. Slow.",
    7: "Medium-wide. Ghibli watercolor. Jaggi (Tamil 25, mustache) balances on one foot at the wall corner, then leaps lightly to the lower slab, laughing softly. Slow.",
    8: "Close. Ghibli watercolor. Jaggi (Tamil 25, mustache) claps mortar dust off his palms and grins out at the town below from the unfinished structure. Slow.",
    9: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache, cream shirt) rides his motorcycle on a long straight neem-lined road, wind in hair, grin wide. Slow.",
    10: "Medium. Ghibli watercolor. Jaggi (Tamil 25, mustache) leans confidently into a hairpin curve, motorcycle and body one motion, eyes bright with delight. Slow.",
    11: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache) carves through a hairpin under flame-of-the-forest trees in bloom, orange petals drifting, laughing aloud. Slow.",
    12: "Medium-wide. Ghibli watercolor. Jaggi (Tamil 25, mustache) glances out over the edge at the Mysore plain spread far below, easy joyful smile. Slow.",
    13: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache, cream shirt) takes the final mountain bend with easy skill, summit clearing ahead. Slow practiced motion.",
    14: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache) brakes lightly on red dirt at the summit clearing, the great granite outcrop ahead, eyes alive. Slow.",
    15: "Medium. Ghibli watercolor. Jaggi (Tamil 25, mustache) swings off his motorcycle in one fluid athletic motion, dry grass underfoot, grin bright. Slow.",
    16: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache, cream shirt) stands beside the motorcycle, hand on warm seat, gazing up at the great granite rock. Slow.",
    17: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache) strides through dry sun-warm grass toward the broad flat granite outcrop, bright open clearing. Slow joyful gait.",
    18: "Close. Ghibli watercolor. Jaggi's palm (Tamil 25 hand) rests fingers-splayed on sun-warm granite, fine warm rock texture filling the frame. Slow.",
    19: "Medium. Ghibli watercolor. Jaggi (Tamil 25, mustache, cream shirt) vaults up onto the great flat rock with athletic ease, wind in his hair. Slow.",
    20: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache) drops cross-legged on the centre of the great rock, hands on knees, eyes wide and grinning at the valley. Slow.",
    21: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache) sits cross-legged on the rock as a pair of black kites circle silently overhead, shadows drifting on stone. Slow.",
    22: "Close. Ghibli watercolor. Jaggi's face (Tamil 25, mustache, deep dark eyes): grin softens, suddenly a quiet wide attention, breath catching. Slow.",
    23: "Medium-close. Ghibli watercolor. Jaggi's palm on warm granite (Tamil 25 hand), the edge between skin and stone visually blurring, painterly. Slow.",
    24: "Close. Ghibli watercolor. Jaggi (Tamil 25, mustache, deep dark eyes): tears begin to brim, wind moving his short black hair, world absorbed into him. Slow.",
    25: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache) sits unmoving on the great granite rock as the sun shifts across the sky and shadows lengthen, breath slow. Slow.",
    26: "Close. Ghibli watercolor. Jaggi (Tamil 25, mustache) on the rock: tears stream freely, mouth softly open between laughter and weeping, eyes shining. Slow.",
    27: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache) cross-legged on the rock as a single black kite drifts past at eye level against the glowing golden valley. Slow.",
    28: "Close. Ghibli watercolor. Jaggi (Tamil 25, mustache, dark eyes) blinks very slowly, tears still on his cheeks, returning from somewhere vast. Slow.",
    29: "Close. Ghibli watercolor. Jaggi's hands (Tamil 25) turn slowly before his face, palms then backs then fingertips, studied like he has never seen hands before. Slow.",
    30: "Medium. Ghibli watercolor. Jaggi (Tamil 25, mustache, cream shirt) climbs down off the great granite outcrop hand by hand, with the care of one learning to walk. Slow.",
    31: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache) stands beside his motorcycle and pushes it along warm red dirt with one hand on the bar, not mounting. Slow.",
    32: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache, cream shirt) pushes the motorcycle down the bending mountain road, flame-of-the-forest petals drifting. Slow.",
    33: "Medium-wide. Ghibli watercolor. Jaggi (Tamil 25, mustache) walks the motorcycle slowly down the empty winding road, golden valley glowing below, face calm and wet. Slow.",
    34: "Wide. Ghibli watercolor. Jaggi (Tamil 25, mustache, cream shirt) small in the distance, pushing his motorcycle along the descending road into the golden Deccan plain. Slow.",
    35: "Close. Ghibli watercolor. Jaggi's hand on the motorcycle handlebar (Tamil 25 hand), his calm changed face visible at frame edge, golden hour light. Slow.",
}

assert len(PROMPTS) == 36
oversized = [(i, len(p)) for i, p in PROMPTS.items() if len(p) > 225]
if oversized:
    print(f"OVERSIZED: {oversized}")
    sys.exit(1)
print(f"all {len(PROMPTS)} prompts within 225-char cap (max: {max(len(p) for p in PROMPTS.values())}c)")


async def main():
    async with async_session_factory() as db:
        proj = (await db.execute(select(Project).where(Project.id == PID))).scalar_one()
        ep0 = (await db.execute(select(Episode).where(Episode.project_id == PID, Episode.order_index == 0))).scalar_one()
        scs = (await db.execute(
            select(Scene).where(Scene.episode_id == ep0.id).order_by(Scene.order_index)
            .options(selectinload(Scene.prompt))
        )).scalars().all()
        print(f"project={proj.status.value} ep#0 scenes={len(scs)}")

        # 1) halt in-flight
        proj.status = ProjectStatus.draft
        await db.commit()
        print("project -> draft (halts in-flight via assert_project_active)")

        # 2) update ScenePrompt.video_prompt in place
        updated = 0
        for s in scs:
            new_p = PROMPTS.get(s.order_index)
            if not new_p:
                continue
            if s.prompt is None:
                from app.models.scene_prompt import ScenePrompt as SP
                sp = SP(scene_id=s.id, video_prompt=new_p)
                db.add(sp)
            else:
                s.prompt.video_prompt = new_p
            updated += 1
        print(f"updated {updated} ScenePrompt.video_prompt rows")

        # 3) reset scene status to 'prompted' so video chord re-renders
        # (chord picks up anything that isn't `generated` and not `failed`)
        for s in scs:
            s.status = SceneStatus.prompted
        print(f"reset {len(scs)} scenes -> prompted")

        await db.commit()

        # 4) set project to generating so /regenerate-videos and chord checks pass
        proj.status = ProjectStatus.generating
        await db.commit()
        print(f"project -> generating")

asyncio.run(main())
