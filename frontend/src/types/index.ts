/** TypeScript types matching the backend Pydantic schemas. */

export type ProjectStatus =
  | 'draft' | 'analyzing' | 'planning' | 'prompting' | 'audio_planning'
  | 'reviewing' | 'image_pregen' | 'generating' | 'stitching' | 'complete' | 'failed';

export type SceneStatus = 'planned' | 'prompted' | 'approved' | 'generating' | 'generated' | 'failed';
export type AssetType = 'scene_video' | 'full_story_audio' | 'final_render' | 'character_ref' | 'background_ref' | 'scene_ref' | 'scene_action' | 'scene_action_2' | 'scene_action_seq' | 'product_ref';
export type AssetStatus = 'pending' | 'generating' | 'complete' | 'failed';
export type JobType = 'story_analysis' | 'scene_planning' | 'prompt_generation' | 'audio_planning' | 'consistency_review' | 'image_pregen' | 'video_generation' | 'audio_generation' | 'stitching' | 'full_pipeline';
export type JobStatus = 'queued' | 'running' | 'complete' | 'failed' | 'cancelled';

export type EpisodeStatus = ProjectStatus;

export type YouTubePrivacy = 'private' | 'unlisted' | 'public';
export type YouTubeUploadStatus = 'queued' | 'uploading' | 'complete' | 'failed';

export interface YouTubeUpload {
  id: string;
  episode_id: string;
  title: string;
  description: string;
  privacy: YouTubePrivacy;
  status: YouTubeUploadStatus;
  youtube_id: string | null;
  youtube_url: string | null;
  progress: number | null;
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface Episode {
  id: string;
  project_id: string;
  order_index: number;
  title: string;
  status: EpisodeStatus;
  theme_hint: string | null;
  original_story_text: string;
  target_duration_seconds: number | null;
  final_audio_duration_seconds: number | null;
  story_summary: string | null;
  beat_list_json: string | null;
  pacing_notes: string | null;
  style_lock: string | null;
  final_evaluation_json: string | null;
  continue_from_previous: boolean;
  skip_audio: boolean;
  youtube_audio_url: string | null;
  youtube_audio_duration_seconds: number | null;
  youtube_as_background_music: boolean;
  final_video_path: string | null;
  scene_count: number;
  created_at: string;
  updated_at: string;
}

export interface EpisodeListItem {
  id: string;
  project_id: string;
  order_index: number;
  title: string;
  status: EpisodeStatus;
  theme_hint: string | null;
  target_duration_seconds: number | null;
  skip_audio: boolean;
  youtube_audio_url: string | null;
  youtube_as_background_music: boolean;
  final_video_path: string | null;
  scene_count: number;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  title: string;
  original_story_text: string;
  status: ProjectStatus;
  total_target_duration_seconds: number | null;
  final_audio_duration_seconds: number | null;
  pipeline_profile: string;
  story_summary: string | null;
  beat_list_json: string | null;
  pacing_notes: string | null;
  style_lock: string | null;
  final_evaluation_json: string | null;
  scene_count: number;
  character_count: number;
  location_count: number;
  created_at: string;
  updated_at: string;
}

export interface ProjectListItem {
  id: string;
  title: string;
  status: ProjectStatus;
  total_target_duration_seconds: number | null;
  pipeline_profile: string;
  scene_count: number;
  created_at: string;
  updated_at: string;
}

export interface PipelineProfile {
  name: string;
  description: string;
  video_provider: string;
  vram_min_gb: number;
  recommended_for: string;
}

export interface LoRAPlan {
  loras: { id: string; weight: number }[];
  shot_type: 'closeup' | 'medium' | 'wide';
  rationale?: string;
}

export interface ScenePrompt {
  id: string;
  scene_id: string;
  video_prompt: string | null;
  negative_prompt: string | null;
  style_notes: string | null;
  camera_plan: string | null;
  camera_angle: string | null;
  subject_description: string | null;
  environment_description: string | null;
  action_description: string | null;
  continuity_guardrails: string | null;
  scene_breakdown: string | null;
  critic_notes: string | null;
  lora_plan_json: string | null;
  lora_plan: LoRAPlan | null;
  approved: boolean;
}

export interface Character {
  id: string;
  project_id: string;
  canonical_name: string;
  physical_description: string | null;
  clothing_description: string | null;
  personality_notes: string | null;
  voice_notes: string | null;
  continuity_notes: string | null;
  reference_image_path: string | null;
}

export interface Scene {
  id: string;
  project_id: string;
  episode_id: string;
  order_index: number;
  source_excerpt: string | null;
  duration_seconds: number;
  scene_purpose: string | null;
  visual_summary: string | null;
  audio_alignment_notes: string | null;
  continuity_from_previous: string | null;
  continuity_to_next: string | null;
  continuity_prev_scene_id: string | null;
  target_audio_segment_start: number | null;
  target_audio_segment_end: number | null;
  caption: string | null;
  location_id: string | null;
  status: SceneStatus;
  locked: boolean;
  prompt: ScenePrompt | null;
  characters: Character[];
  evaluation_json: string | null;
}

export interface Location {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  continuity_notes: string | null;
  reference_image_path: string | null;
}

export interface Product {
  id: string;
  project_id: string;
  canonical_name: string;
  category: string | null;
  physical_description: string | null;
  brand_marks: string | null;
  color_palette: string | null;
  hero_angle: string | null;
  user_uploaded_path: string | null;
  reference_image_path: string | null;
}

export interface AudioPlan {
  id: string;
  project_id: string;
  episode_id: string | null;
  full_story_narration_text: string | null;
  full_story_dialogue_plan: string | null;
  full_story_audio_prompt: string | null;
  ambience_progression_notes: string | null;
  sound_transition_notes: string | null;
  total_estimated_audio_duration: number | null;
  timing_map_json: string | null;
  approved: boolean;
}

export interface Asset {
  id: string;
  project_id: string;
  episode_id: string | null;
  scene_id: string | null;
  asset_type: AssetType;
  file_path: string | null;
  metadata_json: string | null;
  generation_provider: string | null;
  generation_params_json: string | null;
  status: AssetStatus;
  created_at: string;
}

export interface RenderJob {
  id: string;
  project_id: string;
  job_type: JobType;
  status: JobStatus;
  payload_json: string | null;
  result_json: string | null;
  error_text: string | null;
  celery_task_id: string | null;
  job_type_detail: string | null;
  created_at: string;
  updated_at: string;
}

export interface EvaluationMetrics {
  video: string;
  frames_sampled: number;
  clip?: { mean: number; min: number; max: number };
  identity?: { mean: number; frames_with_face: number; ref_face_found: number };
  motion?: { mean_flow_mag: number };
  smoothness?: { mean_ssim: number };
  verdict: string[];
}

export interface EvaluationResult {
  metrics?: EvaluationMetrics;
  suggestion?: {
    current: Record<string, number>;
    deltas: Record<string, number>;
    reasons: string[];
  };
  error?: string;
}

// Images API
export interface CharacterImageItem {
  id: string;
  name: string;
  physical_description: string | null;
  clothing_description: string | null;
  image_url: string | null;
}

export interface LocationImageItem {
  id: string;
  name: string;
  description: string | null;
  image_url: string | null;
}

export interface SceneRefItem {
  id: string;
  order_index: number;
  visual_summary: string | null;
  action_image_url: string | null;
  action_image_2_url: string | null;
  action_image_seq_urls: string[];
  action_image_seq: { url: string; prompt: string | null; negative: string | null }[];
}

export interface ProjectImages {
  project_id: string;
  characters: CharacterImageItem[];
  locations: LocationImageItem[];
  scene_refs: SceneRefItem[];
}

export interface UploadRef {
  asset_id: string;
  project_id: string;
  asset_type: 'character_ref' | 'product_ref';
  file_path: string;
  label: string;
  kind: 'character' | 'product';
  source: 'user_upload';
}
