import type { JsonRecord } from "./common";

export type SpaceType = "home" | "floor" | "room" | "zone";
export type SpaceStatus = "active" | "inactive" | "archived";
export type AssignmentType =
  "fixed_installation" | "current_placement" | "observed_presence" | "user_asserted";

export interface Space {
  id: string;
  parent_id: string | null;
  space_type: SpaceType;
  name: string;
  normalized_name: string;
  slug: string;
  path: string;
  sort_order: number;
  external_space_id: string | null;
  external_source: string | null;
  status: SpaceStatus;
  geometry: JsonRecord | null;
  metadata: JsonRecord;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

export interface SpaceTreeNode extends Space {
  children: SpaceTreeNode[];
}

export interface AssignedDevice {
  device_id: string;
  entity_id: string;
  adapter_id: string;
  external_id: string;
  name: string;
  device_type: string;
  is_online: boolean;
  is_enabled: boolean;
  assignment_id: string;
  assignment_type: AssignmentType;
  valid_from: string;
  valid_until: string | null;
  confidence: number | null;
  source_type: string;
  source_id: string | null;
  reason: string | null;
}

export interface AssignmentHistoryItem {
  id: string;
  entity_id: string;
  device_id: string | null;
  space_id: string;
  space_name: string;
  space_path: string;
  assignment_type: AssignmentType;
  valid_from: string;
  valid_until: string | null;
  confidence: number | null;
  source_type: string;
  source_id: string | null;
  source_observation_id: string | null;
  reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface SpaceCreateRequest {
  parent_id: string;
  name: string;
  space_type: Exclude<SpaceType, "home">;
  sort_order?: number;
  metadata?: JsonRecord;
}

export interface SpaceUpdateRequest {
  name?: string;
  sort_order?: number;
  status?: SpaceStatus;
}

export interface DeviceAssignmentRequest {
  space_id: string;
  assignment_type: AssignmentType;
  confidence?: number;
  reason?: string;
}
