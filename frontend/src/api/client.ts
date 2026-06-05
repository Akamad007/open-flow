/** API client for the OpenFlow backend. */

const BASE = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options?.headers || {}) },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`API ${res.status}: ${text}`);
  }
  if (res.status === 204) return undefined as unknown as T;
  return res.json();
}

export const api = {
  // Projects
  listProjects: () => request<import('../types').ProjectListItem[]>('/projects'),
  getProject: (id: string) => request<import('../types').Project>(`/projects/${id}`),
  listPipelines: () => request<import('../types').PipelineProfile[]>('/pipelines'),
  createProject: (data: {
    title: string; original_story_text: string; total_target_duration_seconds: number;
    pipeline_profile?: string; theme_hint?: string; youtube_audio_url?: string;
    skip_audio?: boolean; youtube_as_background_music?: boolean;
  }) =>
    request<import('../types').Project>('/projects', { method: 'POST', body: JSON.stringify(data) }),
  updateProject: (id: string, data: Record<string, unknown>) =>
    request<import('../types').Project>(`/projects/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: 'DELETE' }),

  // Episodes
  listEpisodes: (projectId: string) =>
    request<import('../types').EpisodeListItem[]>(`/projects/${projectId}/episodes`),
  getEpisode: (episodeId: string) =>
    request<import('../types').Episode>(`/episodes/${episodeId}`),
  createEpisode: (projectId: string, data: {
    title?: string; theme_hint?: string; original_story_text?: string;
    target_duration_seconds?: number; continue_from_previous?: boolean;
    skip_audio?: boolean; youtube_audio_url?: string;
    youtube_as_background_music?: boolean;
  }) => request<import('../types').Episode>(`/projects/${projectId}/episodes`, {
    method: 'POST', body: JSON.stringify(data),
  }),
  createEpisodeFromTheme: (projectId: string, data: {
    theme_hint: string; title?: string;
    target_duration_seconds?: number; continue_from_previous?: boolean;
    skip_audio?: boolean; youtube_audio_url?: string;
  }) => request<import('../types').Episode>(`/projects/${projectId}/episodes/from-theme`, {
    method: 'POST', body: JSON.stringify(data),
  }),
  updateEpisode: (episodeId: string, data: Record<string, unknown>) =>
    request<import('../types').Episode>(`/episodes/${episodeId}`, {
      method: 'PATCH', body: JSON.stringify(data),
    }),
  deleteEpisode: (episodeId: string) =>
    request<void>(`/episodes/${episodeId}`, { method: 'DELETE' }),
  attachYoutubeAudio: (episodeId: string, youtubeUrl: string, mode: 'replace' | 'mix' = 'replace') =>
    request<import('../types').Episode>(`/episodes/${episodeId}/attach-youtube-audio`, {
      method: 'POST', body: JSON.stringify({ youtube_audio_url: youtubeUrl, mode }),
    }),
  uploadEpisodeToYoutube: (episodeId: string, data: {
    title: string; description: string; privacy: 'private' | 'unlisted' | 'public';
  }) =>
    request<import('../types').YouTubeUpload>(`/episodes/${episodeId}/upload-youtube`, {
      method: 'POST', body: JSON.stringify(data),
    }),
  listEpisodeYoutubeUploads: (episodeId: string) =>
    request<import('../types').YouTubeUpload[]>(`/episodes/${episodeId}/uploads`),
  suggestYoutubeMetadata: (episodeId: string) =>
    request<{ title: string; description: string }>(`/episodes/${episodeId}/youtube-metadata`, {
      method: 'POST',
    }),

  // Scenes
  listScenes: (projectId: string) => request<import('../types').Scene[]>(`/projects/${projectId}/scenes`),
  getScene: (id: string) => request<import('../types').Scene>(`/scenes/${id}`),
  updateScene: (id: string, data: Record<string, unknown>) =>
    request<import('../types').Scene>(`/scenes/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  updateScenePrompt: (id: string, data: Record<string, unknown>) =>
    request<import('../types').Scene>(`/scenes/${id}/prompt`, { method: 'PUT', body: JSON.stringify(data) }),
  reorderScenes: (projectId: string, sceneIds: string[]) =>
    request<import('../types').Scene[]>(`/projects/${projectId}/scenes/reorder`, { method: 'POST', body: JSON.stringify({ scene_ids: sceneIds }) }),

  // Characters & Locations
  listCharacters: (projectId: string) => request<import('../types').Character[]>(`/projects/${projectId}/characters`),
  updateCharacter: (id: string, data: Record<string, unknown>) =>
    request<import('../types').Character>(`/characters/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  listLocations: (projectId: string) => request<import('../types').Location[]>(`/projects/${projectId}/locations`),
  updateLocation: (id: string, data: Record<string, unknown>) =>
    request<import('../types').Location>(`/locations/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  // Audio Plan
  getAudioPlan: (projectId: string) => request<import('../types').AudioPlan | null>(`/projects/${projectId}/audio-plan`),
  getEpisodeAudioPlan: (episodeId: string) => request<import('../types').AudioPlan | null>(`/episodes/${episodeId}/audio-plan`),
  updateAudioPlan: (id: string, data: Record<string, unknown>) =>
    request<import('../types').AudioPlan>(`/audio-plans/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  // Assets, Jobs & Images
  listAssets: (projectId: string) => request<import('../types').Asset[]>(`/projects/${projectId}/assets`),
  listJobs: (projectId: string) => request<import('../types').RenderJob[]>(`/projects/${projectId}/jobs`),
  getJob: (id: string) => request<import('../types').RenderJob>(`/jobs/${id}`),
  getProjectImages: (projectId: string) => request<import('../types').ProjectImages>(`/projects/${projectId}/images`),

  // Generation triggers
  analyzeStory: (projectId: string) => request<{ job_id: string }>(`/projects/${projectId}/analyze`, { method: 'POST' }),
  planScenes: (projectId: string) => request<{ job_id: string }>(`/projects/${projectId}/plan-scenes`, { method: 'POST' }),
  generatePrompts: (projectId: string) => request<{ job_id: string }>(`/projects/${projectId}/generate-prompts`, { method: 'POST' }),
  planAudio: (projectId: string) => request<{ job_id: string }>(`/projects/${projectId}/plan-audio`, { method: 'POST' }),
  reviewConsistency: (projectId: string) => request<{ job_id: string }>(`/projects/${projectId}/review`, { method: 'POST' }),
  generateVideos: (projectId: string) => request<{ job_id: string }>(`/projects/${projectId}/generate-videos`, { method: 'POST' }),
  generateAudio: (projectId: string) => request<{ job_id: string }>(`/projects/${projectId}/generate-audio`, { method: 'POST' }),
  stitch: (projectId: string) => request<{ job_id: string }>(`/projects/${projectId}/stitch`, { method: 'POST' }),
  generateAll: (projectId: string) => request<{ job_id: string }>(`/projects/${projectId}/generate-all`, { method: 'POST' }),
  regenerateScene: (sceneId: string) => request<{ job_id: string }>(`/scenes/${sceneId}/regenerate`, { method: 'POST' }),
  regenerateAllVideos: (projectId: string) => request<{ job_id: string }>(`/projects/${projectId}/regenerate-videos`, { method: 'POST' }),
  regenerateAllImages: (projectId: string) => request<{ job_id: string }>(`/projects/${projectId}/regenerate-images`, { method: 'POST' }),

  // Celery log tail (filtered to lines mentioning project_id)
  getProjectCeleryLog: (projectId: string, tail = 300) =>
    request<{ project_id: string; lines: string[]; count: number }>(`/projects/${projectId}/celery-log?tail=${tail}`),

  // User uploads — character + product reference images
  uploadCharacter: async (projectId: string, label: string, file: File): Promise<import('../types').UploadRef> => {
    const fd = new FormData();
    fd.append('label', label);
    fd.append('file', file);
    const res = await fetch(`${BASE}/projects/${projectId}/uploads/character`, { method: 'POST', body: fd });
    if (!res.ok) throw new Error(`Upload failed: ${res.status} ${await res.text()}`);
    return res.json();
  },
  uploadProduct: async (projectId: string, label: string, file: File): Promise<import('../types').UploadRef> => {
    const fd = new FormData();
    fd.append('label', label);
    fd.append('file', file);
    const res = await fetch(`${BASE}/projects/${projectId}/uploads/product`, { method: 'POST', body: fd });
    if (!res.ok) throw new Error(`Upload failed: ${res.status} ${await res.text()}`);
    return res.json();
  },
  listUploads: (projectId: string) =>
    request<import('../types').UploadRef[]>(`/projects/${projectId}/uploads`),
  deleteUpload: (projectId: string, assetId: string) =>
    request<void>(`/projects/${projectId}/uploads/${assetId}`, { method: 'DELETE' }),
};
