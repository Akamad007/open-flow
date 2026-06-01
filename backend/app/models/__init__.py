"""ORM models package — import all models so Alembic can discover them."""

from app.models.project import Project
from app.models.episode import Episode, EpisodeStatus
from app.models.character import Character
from app.models.location import Location
from app.models.product import Product
from app.models.scene import Scene, scene_characters, scene_products
from app.models.scene_prompt import ScenePrompt
from app.models.audio_plan import AudioPlan
from app.models.asset import Asset
from app.models.render_job import RenderJob
from app.models.youtube_upload import YouTubePrivacy, YouTubeUpload, YouTubeUploadStatus

__all__ = [
    "Project",
    "Episode",
    "EpisodeStatus",
    "Character",
    "Location",
    "Product",
    "Scene",
    "scene_characters",
    "scene_products",
    "ScenePrompt",
    "AudioPlan",
    "Asset",
    "RenderJob",
    "YouTubeUpload",
    "YouTubePrivacy",
    "YouTubeUploadStatus",
]
