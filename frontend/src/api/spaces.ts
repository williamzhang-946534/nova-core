import { buildQueryString, requestJson } from "./client";
import type {
  AssignedDevice,
  AssignmentHistoryItem,
  DeviceAssignmentRequest,
  EnvironmentOverview,
  QueriedEntitySummary,
  QueriedSpaceSummary,
  QueryExplanation,
  QuerySourceSummary,
  Space,
  SpaceCreateRequest,
  SpaceTreeNode,
  SpaceUpdateRequest,
  StateCoverage,
  StateEstimate,
  StateEstimateEvidence,
} from "@/types/spaces";
import {
  isBoolean,
  isJsonValue,
  isNumber,
  isNumberOrNull,
  isOneOf,
  isRecord,
  isRecordOrNull,
  isString,
  isStringArray,
} from "@/utils/validation";

const spaceTypes = ["home", "floor", "room", "zone"] as const;
const spaceStatuses = ["active", "inactive", "archived"] as const;
const assignmentTypes = [
  "fixed_installation",
  "current_placement",
  "observed_presence",
  "user_asserted",
] as const;
const stateStatuses = [
  "observed",
  "derived",
  "inferred",
  "unknown",
  "stale",
  "unavailable",
  "conflict",
] as const;
const coverageStatuses = ["covered", "partial", "blind", "lost"] as const;

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

function isStringOrNull(value: unknown): value is string | null {
  return value === null || isString(value);
}

function isRuleInfo(value: unknown): value is StateEstimate["rule"] {
  return isRecord(value) && isString(value.id) && isString(value.version);
}

function isStateEstimate(value: unknown): value is StateEstimate {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.target_id) &&
    isString(value.environment_id) &&
    isString(value.target_type) &&
    isStringOrNull(value.entity_id) &&
    isStringOrNull(value.space_id) &&
    isString(value.attribute) &&
    isOneOf(value.status, stateStatuses) &&
    isJsonValue(value.value) &&
    isStringOrNull(value.unit) &&
    isNumberOrNull(value.confidence) &&
    isRecord(value.evidence_summary) &&
    isRecordOrNull(value.conflict_details) &&
    isRuleInfo(value.rule) &&
    isString(value.input_cutoff_at) &&
    isString(value.effective_from) &&
    isString(value.generated_at) &&
    isStringOrNull(value.valid_until) &&
    isStringOrNull(value.superseded_at) &&
    isString(value.created_at)
  );
}

function isQueriedSpace(value: unknown): value is QueriedSpaceSummary {
  return (
    isRecord(value) &&
    isString(value.space_id) &&
    isStringOrNull(value.parent_id) &&
    isString(value.space_type) &&
    isString(value.name) &&
    isStringArray(value.path) &&
    isString(value.status) &&
    isStringArray(value.state_ids)
  );
}

function isQueriedEntity(value: unknown): value is QueriedEntitySummary {
  return (
    isRecord(value) &&
    isString(value.entity_id) &&
    isString(value.name) &&
    isString(value.entity_type) &&
    isStringOrNull(value.device_id) &&
    isStringOrNull(value.space_id) &&
    isStringArray(value.state_ids)
  );
}

function isStateCoverage(value: unknown): value is StateCoverage {
  return (
    isRecord(value) &&
    isString(value.space_id) &&
    isString(value.attribute) &&
    isOneOf(value.coverage, coverageStatuses) &&
    (value.state_status === null || isOneOf(value.state_status, stateStatuses)) &&
    isNumber(value.source_count) &&
    isString(value.explanation)
  );
}

function isQuerySource(value: unknown): value is QuerySourceSummary {
  return (
    isRecord(value) &&
    isString(value.source_id) &&
    isStringOrNull(value.source_type) &&
    isNumber(value.observation_count) &&
    isStringArray(value.entity_ids) &&
    isStringArray(value.observation_ids)
  );
}

function isQueryExplanation(value: unknown): value is QueryExplanation {
  return (
    isRecord(value) &&
    isOneOf(value.status, stateStatuses) &&
    isStringOrNull(value.space_id) &&
    isStringOrNull(value.entity_id) &&
    isString(value.attribute) &&
    isString(value.message) &&
    isRecord(value.details)
  );
}

function isEvidence(value: unknown): value is StateEstimateEvidence {
  return (
    isRecord(value) &&
    isString(value.observation_id) &&
    isString(value.source_id) &&
    isString(value.source_type) &&
    isStringOrNull(value.entity_id) &&
    isStringOrNull(value.space_id) &&
    isString(value.attribute) &&
    isJsonValue(value.normalized_value) &&
    isStringOrNull(value.normalized_unit) &&
    isStringOrNull(value.observed_at) &&
    isStringOrNull(value.observed_at_source) &&
    isString(value.received_at) &&
    isString(value.quality_status) &&
    isString(value.contribution) &&
    isNumberOrNull(value.weight) &&
    isStringOrNull(value.exclusion_reason)
  );
}

function isEnvironmentOverview(value: unknown): value is EnvironmentOverview {
  return (
    isRecord(value) &&
    isBoolean(value.service_available) &&
    isStringOrNull(value.environment_id) &&
    isStringOrNull(value.environment_name) &&
    isStringOrNull(value.root_space_id) &&
    (value.selected_space === null || isQueriedSpace(value.selected_space)) &&
    Array.isArray(value.spaces) &&
    value.spaces.every(isQueriedSpace) &&
    Array.isArray(value.entities) &&
    value.entities.every(isQueriedEntity) &&
    Array.isArray(value.states) &&
    value.states.every(isStateEstimate) &&
    Array.isArray(value.coverage) &&
    value.coverage.every(isStateCoverage) &&
    Array.isArray(value.sources) &&
    value.sources.every(isQuerySource) &&
    Array.isArray(value.explanations) &&
    value.explanations.every(isQueryExplanation) &&
    Array.isArray(value.evidence) &&
    value.evidence.every(isEvidence) &&
    isStringArray(value.attributes) &&
    isBoolean(value.include_descendants) &&
    isString(value.generated_at)
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

export function getSpaceOverview(
  spaceId: string,
  options: { includeDescendants?: boolean; includeEvidence?: boolean } = {},
): Promise<EnvironmentOverview> {
  return requestJson<{ data: EnvironmentOverview }>(
    `/api/spaces/${encodeURIComponent(spaceId)}/overview${buildQueryString({
      include_descendants: options.includeDescendants ?? true,
      include_evidence: options.includeEvidence ?? false,
    })}`,
    (value): value is { data: EnvironmentOverview } =>
      isRecord(value) && isRecord(value.data) && isEnvironmentOverview(value.data),
  ).then((response) => response.data);
}

export function getSpaceCoverage(
  spaceId: string,
  includeDescendants = false,
): Promise<StateCoverage[]> {
  return requestJson<{ data: StateCoverage[] }>(
    `/api/spaces/${encodeURIComponent(spaceId)}/coverage${buildQueryString({
      include_descendants: includeDescendants,
    })}`,
    (value): value is { data: StateCoverage[] } =>
      isRecord(value) && Array.isArray(value.data) && value.data.every(isStateCoverage),
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
