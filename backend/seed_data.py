#!/usr/bin/env python3
"""
Seed the database with a sample project and story for testing.

Usage:
    cd backend
    python seed_data.py
"""

import asyncio
import uuid

from sqlalchemy import text

from app.database import async_session_factory, engine, Base
from app.models.project import Project, ProjectStatus

SAMPLE_STORY = """
The old lighthouse keeper climbed the spiral staircase for the last time. His weathered hands gripped the iron railing, each step echoing through the stone tower like a heartbeat winding down. Sixty years he had tended this light — sixty years of storms and silence, of ships passing safely through the dark.

At the top, the great lens waited. Three tons of hand-ground glass and brass, turning endlessly on a bed of mercury. He placed his calloused palm against the cool surface and felt the vibration of the mechanism, steady as always.

Through the window, the Atlantic stretched to the horizon. A November storm was building — dark clouds stacking like battlements above the grey water. The first rain began to tap against the glass, gentle at first, then driving.

He lit the lamp one final time. The flame caught, flickered, then blazed. The lens began its slow rotation, sending a beam of white light sweeping across the churning sea. For a moment, everything was as it had always been — the light, the storm, the keeper watching over the water.

Tomorrow, they would come with their computers and their automation. The light would still turn, but no one would be here to watch it. No one would hear the storm or smell the salt or feel the tower sway in the wind.

He sat in his chair by the window, wrapped in a wool blanket, and watched the beam cut through the darkness. One last night. The sea crashed against the rocks below, and the old keeper kept his vigil, as he always had, as he always would until the dawn.
""".strip()


async def seed():
    """Create tables and insert sample data."""
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as db:
        # Check if sample exists
        result = await db.execute(
            text("SELECT COUNT(*) FROM projects WHERE title = 'The Last Lighthouse Keeper'")
        )
        count = result.scalar()
        if count and count > 0:
            print("Sample project already exists.")
            return

        project = Project(
            id=uuid.uuid4(),
            title="The Last Lighthouse Keeper",
            original_story_text=SAMPLE_STORY,
            status=ProjectStatus.draft,
        )
        db.add(project)
        await db.commit()
        print(f"Created sample project: {project.id}")
        print(f"  Title: {project.title}")
        print(f"  Story length: {len(SAMPLE_STORY)} chars")


if __name__ == "__main__":
    asyncio.run(seed())
