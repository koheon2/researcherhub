export type ResearchField = string;

export interface Researcher {
  id: string;
  name: string;
  institution: string | null;
  country: string | null;
  lat: number | null;
  lng: number | null;
  citations: number;
  h_index: number;
  works_count: number;
  recent_papers: number;
  field: string | null;
  umap_x: number | null;
  umap_y: number | null;
  openalex_url: string | null;
}

export const FIELD_COLORS: Record<string, string> = {
  "AI": "#00d4ff",
  "Computer Vision": "#22c55e",
  "NLP": "#a855f7",
  "HCI": "#f97316",
  "Theory & Math": "#eab308",
  "Robotics": "#ef4444",
  "EE": "#f43f5e",
  "Networks": "#06b6d4",
  "Signal Processing": "#d97706",
  "Information Systems": "#10b981",
  "Software Engineering": "#8b5cf6",
  "Hardware": "#64748b",
  "Computer Science": "#94a3b8",
};

export function getFieldColor(field: string | null): string {
  if (!field) return "#64748b";
  return FIELD_COLORS[field] ?? "#64748b";
}
