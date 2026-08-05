export interface Memory {
  id: string;
  memory: string;
  user_id?: string;
  agent_id?: string;
  created_at?: string;
  updated_at?: string;
}

export interface ApiKey {
  id: string;
  label: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiKeyCreateResponse {
  id: string;
  label: string;
  key: string;
  key_prefix: string;
  created_at: string;
}

export interface ApiRequestLog {
  id: string;
  created_at: string;
  method: string;
  path: string;
  status_code: number;
  latency_ms: number;
  auth_type: string;
}

export type EntityType = "user" | "agent" | "run" | "project";

export interface Entity {
  id: string;
  type: EntityType;
  total_memories: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface MemoryExport {
  id: string;
  format: "json" | "csv";
  filters: Record<string, string>;
  status: string;
  record_count: number;
  created_at: string;
  completed_at?: string | null;
}

export interface TimelineEvent {
  id: string;
  event_type: string;
  source_agent: string;
  user_id?: string | null;
  agent_id?: string | null;
  run_id?: string | null;
  project?: string | null;
  summary?: string | null;
  payload?: Record<string, unknown> | null;
  category?: string | null;
  memory_ids: string[];
  created_at: string;
}
