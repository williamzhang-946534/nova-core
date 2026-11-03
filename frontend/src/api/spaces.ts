import { buildQueryString, requestJson } from "./client";
import type {
  AssignedDevice,
  AssignmentHistoryItem,
  DeviceAssignmentRequest,
  Space,
  SpaceCreateRequest,
  SpaceTreeNode,
  SpaceUpdateRequest,
} from "@/types/spaces";
import {
  isBoolean,
  isNumber,
  isNumberOrNull,
  isOneOf,
  isRecord,
  isRecordOrNull,
  isString,
} from "@/utils/validation";

const spaceTypes = ["home", "floor", "room", "zone"] as const;
const spaceStatuses = ["active", "inactive", "archived"] as const;
const assignmentTypes = [
  "fixed_installation",
  "current_placement",
  "observed_presence",
  "user_asserted",
] as const;

function isSpace(value: unknown): value is Space {
  return (
    isRecord(value) &&
    isString(value.id) &&
    (value.parent_id === null || isString(value.parent_id)) &&
    isOneOf(value.space_type, spaceTypes) &&
    isString(value.name) &&
    isString(value.normalized_name) &&
    isString(value.slug) &&
    isString(value.path) &&
    isNumber(value.sort_order) &&
    (value.external_space_id === null || isString(value.external_space_id)) &&
    (value.external_source === null || isString(value.external_source)) &&
    isOneOf(value.status, spaceStatuses) &&
    isRecordOrNull(value.geometry) &&
    isRecord(value.metadata) &&
    isString(value.created_at) &&
    isString(value.updated_at) &&
    (value.archived_at === null || isString(value.archived_at))
  );
}

function isSpaceTreeNode(value: unknown): value is SpaceTreeNode {
  return (
    isSpace(value) &&
    Array.isArray((value as SpaceTreeNode).children) &&
    (value as SpaceTreeNode).children.every(isSpaceTreeNode)
  );
}

function isAssignedDevice(value: unknown): value is AssignedDevice {
  return (
    isRecord(value) &&
    isString(value.device_id) &&
    isString(value.entity_id) &&
    isString(value.adapter_id) &&
    isString(value.external_id) &&
    isString(value.name) &&
    isString(value.device_type) &&
    isBoolean(value.is_online) &&
    isBoolean(value.is_enabled) &&
    isString(value.assignment_id) &&
    isOneOf(value.assignment_type, assignmentTypes) &&
    isString(value.valid_from) &&
    (value.valid_until === null || isString(value.valid_until)) &&
    isNumberOrNull(value.confidence) &&
    isString(value.source_type) &&
    (value.source_id === null || isString(value.source_id)) &&
    (value.reason === null || isString(value.reason))
  );
}

function isAssignmentHistory(value: unknown): value is AssignmentHistoryItem {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.entity_id) &&
    (value.device_id === null || isString(value.device_id)) &&
    isString(value.space_id) &&
    isString(value.space_name) &&
    isString(value.space_path) &&
    isOneOf(value.assignment_type, assignmentTypes) &&
    isString(value.valid_from) &&
    (value.valid_until === null || isString(value.valid_until)) &&
    isNumberOrNull(value.confidence) &&
    isString(value.source_type) &&
    (value.source_id === null || isString(value.source_id)) &&
    (value.source_observation_id === null || isString(value.source_observation_id)) &&
    (value.reason === null || isString(value.reason)) &&
    isString(value.created_at) &&
    isString(value.updated_at)
  );
}

export function getSpaceTree(): Promise<SpaceTreeNode> {
  return requestJson<{ data: SpaceTreeNode }>(
    "/api/spaces/tree",
    (value): value is { data: SpaceTreeNode } =>
      isRecord(value) && isRecord(value.data) && isSpaceTreeNode(value.data),
  ).then((response) => response.data);
}

export function createSpace(request: SpaceCreateRequest): Promise<Space> {
  return requestJson<{ data: Space }>(
    "/api/spaces",
    (value): value is { data: Space } =>
      isRecord(value) && isRecord(value.data) && isSpace(value.data),
    { method: "POST", body: request },
  ).then((response) => response.data);
}

export function updateSpace(spaceId: string, request: SpaceUpdateRequest): Promise<Space> {
  return requestJson<{ data: Space }>(
    `/api/spaces/${encodeURIComponent(spaceId)}`,
    (value): value is { data: Space } =>
      isRecord(value) && isRecord(value.data) && isSpace(value.data),
    { method: "PATCH", body: request },
  ).then((response) => response.data);
}

export function moveSpace(spaceId: string, newParentId: string): Promise<Space> {
  return requestJson<{ data: Space }>(
    `/api/spaces/${encodeURIComponent(spaceId)}/move`,
    (value): value is { data: Space } =>
      isRecord(value) && isRecord(value.data) && isSpace(value.data),
    { method: "POST", body: { new_parent_id: newParentId } },
  ).then((response) => response.data);
}

export function archiveSpace(spaceId: string): Promise<Space> {
  return requestJson<{ data: Space }>(
    `/api/spaces/${encodeURIComponent(spaceId)}/archive`,
    (value): value is { data: Space } =>
      isRecord(value) && isRecord(value.data) && isSpace(value.data),
    { method: "POST" },
  ).then((response) => response.data);
}

export function listSpaceDevices(
  spaceId: string,
  includeDescendants: boolean,
): Promise<AssignedDevice[]> {
  return requestJson<{ data: AssignedDevice[] }>(
    `/api/spaces/${encodeURIComponent(spaceId)}/devices${buildQueryString({
      include_descendants: includeDescendants,
    })}`,
    (value): value is { data: AssignedDevice[] } =>
      isRecord(value) && Array.isArray(value.data) && value.data.every(isAssignedDevice),
  ).then((response) => response.data);
}

export function assignDeviceSpace(
  deviceId: string,
  request: DeviceAssignmentRequest,
): Promise<AssignmentHistoryItem> {
  return requestJson<{ data: { assignment: AssignmentHistoryItem } }>(
    `/api/devices/${encodeURIComponent(deviceId)}/assignment`,
    (value): value is { data: { assignment: AssignmentHistoryItem } } =>
      isRecord(value) &&
      isRecord(value.data) &&
      isRecord(value.data.assignment) &&
      isAssignmentHistory(value.data.assignment),
    { method: "POST", body: request },
  ).then((response) => response.data.assignment);
}

export function getDeviceSpaceHistory(deviceId: string): Promise<AssignmentHistoryItem[]> {
  return requestJson<{ data: AssignmentHistoryItem[] }>(
    `/api/devices/${encodeURIComponent(deviceId)}/space-history`,
    (value): value is { data: AssignmentHistoryItem[] } =>
      isRecord(value) && Array.isArray(value.data) && value.data.every(isAssignmentHistory),
  ).then((response) => response.data);
}
