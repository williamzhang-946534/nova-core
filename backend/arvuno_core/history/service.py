import asyncio
import math
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from arvuno_core.history.errors import (
    HistoryNotFoundError,
    HistoryQueryUnsupportedError,
    HistoryValidationError,
)
from arvuno_core.history.models import (
    CorrelatedHistory,
    EntityHistoryResult,
    EnvironmentSnapshotView,
    HistoryQueryResult,
    HistoryRecord,
    HistoryTimeRange,
    NaturalHistoryAnswer,
    NaturalHistoryInterpretation,
    QueryTimeBasis,
    SnapshotDiffEntry,
    SnapshotDiffResult,
    SnapshotLookupResult,
    SpatialHistoryResult,
    TimeGap,
    TimeSemantics,
    TrendQueryResult,
    TrendStatistics,
)
from arvuno_core.history.store import HistoryStore, SqlAlchemyHistoryStore
from arvuno_core.persistence.models import (
    EntitySpaceAssignment,
    EnvironmentSnapshot,
    Event,
    Observation,
    Task,
)
from arvuno_core.persistence.unit_of_work import SqlAlchemyUnitOfWork

UnitOfWorkFactory = Callable[[], SqlAlchemyUnitOfWork]
MAX_RANGE_DAYS = 400
PHYSICAL_ATTRIBUTES = {"temperature", "humidity", "motion", "occupancy", "contact", "illuminance"}
DEVICE_COMMAND_ATTRIBUTES = {"mode", "target_temperature", "target_humidity", "power"}


class HistoryService:
    """Read-only environmental history and limited snapshot comparison."""

    def __init__(
        self,
        unit_of_work_factory: UnitOfWorkFactory,
        *,
        environment_name: str = "home",
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._environment_name = environment_name

    async def time_range(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        timezone: str = "UTC",
        entity_id: str | None = None,
        space_id: str | None = None,
        include_descendants: bool = True,
        attribute: str | None = None,
        quality_status: str | None = None,
        expected_interval_seconds: int | None = None,
        limit: int = 500,
    ) -> HistoryQueryResult:
        return await asyncio.to_thread(
            self._time_range,
            start_time,
            end_time,
            timezone,
            entity_id,
            space_id,
            include_descendants,
            attribute,
            quality_status,
            expected_interval_seconds,
            limit,
        )

    async def spatial_history(
        self,
        space_id: str,
        *,
        start_time: datetime,
        end_time: datetime,
        timezone: str = "UTC",
        include_descendants: bool = True,
        attribute: str | None = None,
        expected_interval_seconds: int | None = None,
        limit: int = 500,
    ) -> SpatialHistoryResult:
        return await asyncio.to_thread(
            self._spatial_history,
            space_id,
            start_time,
            end_time,
            timezone,
            include_descendants,
            attribute,
            expected_interval_seconds,
            limit,
        )

    async def entity_history(
        self,
        entity_id: str,
        *,
        start_time: datetime,
        end_time: datetime,
        timezone: str = "UTC",
        attribute: str | None = None,
        expected_interval_seconds: int | None = None,
        limit: int = 500,
    ) -> EntityHistoryResult:
        return await asyncio.to_thread(
            self._entity_history,
            entity_id,
            start_time,
            end_time,
            timezone,
            attribute,
            expected_interval_seconds,
            limit,
        )

    async def trends(
        self,
        *,
        start_time: datetime,
        end_time: datetime,
        attribute: str,
        timezone: str = "UTC",
        group_by: str = "space",
        space_id: str | None = None,
        entity_id: str | None = None,
        include_descendants: bool = True,
        limit: int = 1000,
    ) -> TrendQueryResult:
        return await asyncio.to_thread(
            self._trends,
            start_time,
            end_time,
            attribute,
            timezone,
            group_by,
            space_id,
            entity_id,
            include_descendants,
            limit,
        )

    async def snapshot_at(
        self,
        *,
        at_time: datetime,
        timezone: str = "UTC",
        environment_id: str | None = None,
        nearest: bool = False,
    ) -> SnapshotLookupResult:
        return await asyncio.to_thread(
            self._snapshot_at,
            at_time,
            timezone,
            environment_id,
            nearest,
        )

    async def snapshot_diff(
        self,
        *,
        baseline_id: str | None = None,
        target_id: str | None = None,
        baseline_at: datetime | None = None,
        target_at: datetime | None = None,
        timezone: str = "UTC",
    ) -> SnapshotDiffResult:
        return await asyncio.to_thread(
            self._snapshot_diff,
            baseline_id,
            target_id,
            baseline_at,
            target_at,
            timezone,
        )

    async def correlate(
        self,
        *,
        record_type: str,
        record_id: str,
        timezone: str = "UTC",
    ) -> CorrelatedHistory:
        return await asyncio.to_thread(
            self._correlate,
            record_type,
            record_id,
            timezone,
        )

    async def ask(
        self,
        query: str,
        *,
        timezone: str = "Asia/Shanghai",
        now: datetime | None = None,
    ) -> NaturalHistoryAnswer:
        return await asyncio.to_thread(self._ask, query, timezone, now)

    def _time_range(
        self,
        start_time: datetime,
        end_time: datetime,
        timezone: str,
        entity_id: str | None,
        space_id: str | None,
        include_descendants: bool,
        attribute: str | None,
        quality_status: str | None,
        expected_interval_seconds: int | None,
        limit: int,
    ) -> HistoryQueryResult:
        def execute(store: HistoryStore) -> HistoryQueryResult:
            start, end, tz_name = _validated_range(start_time, end_time, timezone)
            observations = store.observations(
                start_time=start,
                end_time=end,
                entity_id=entity_id,
                space_id=space_id,
                include_descendants=include_descendants,
                attribute=attribute,
                quality_status=quality_status,
                limit=limit,
            )
            events = store.events(start_time=start, end_time=end, limit=limit)
            tasks = store.tasks(start_time=start, end_time=end, limit=limit)
            records = _localize_records(
                [
                    *_observation_records(observations),
                    *_event_records(events),
                    *_task_records(tasks),
                ],
                tz_name,
            )
            records.sort(key=_record_order)
            records = records[:limit]
            result_range = _range(start, end, tz_name)
            semantics = _semantics(observations, timezone=tz_name, basis="received_at")
            return HistoryQueryResult(
                range=result_range,
                time_semantics=semantics,
                records=records,
                counts={
                    "observation": len(observations),
                    "event": len(events),
                    "task": len(tasks),
                },
                missing_ranges=_missing_ranges(
                    observations,
                    start,
                    end,
                    expected_interval_seconds,
                    semantics,
                ),
                warnings=_range_warnings(start, end, observations),
                generated_at=_utc(datetime.now(UTC)),
            )

        return self._run(execute)

    def _spatial_history(
        self,
        space_id: str,
        start_time: datetime,
        end_time: datetime,
        timezone: str,
        include_descendants: bool = True,
        attribute: str | None = None,
        expected_interval_seconds: int | None = None,
        limit: int = 500,
    ) -> SpatialHistoryResult:
        def execute(store: HistoryStore) -> SpatialHistoryResult:
            start, end, tz_name = _validated_range(start_time, end_time, timezone)
            space = store.space(space_id)
            if space is None:
                raise HistoryNotFoundError("The space does not exist.")
            descendants = store.descendant_space_ids(space_id) if include_descendants else []
            observations = store.observations(
                start_time=start,
                end_time=end,
                space_id=space_id,
                include_descendants=include_descendants,
                attribute=attribute,
                limit=limit,
            )
            assignments = [
                row
                for row in store.entity_assignments(space_id=space_id)
                if (include_descendants or row.space_id == space_id)
                and _utc(row.valid_from) <= end
                and (row.valid_until is None or _utc(row.valid_until) > start)
            ]
            subject_ids = {row.entity_id for row in assignments}
            events = [
                event
                for event in store.events(start_time=start, end_time=end, limit=limit * 4)
                if event.subject_id in subject_ids
            ][:limit]
            correlations = {
                value
                for value in (
                    *[observation.correlation_id for observation in observations],
                    *[event.correlation_id for event in events],
                )
                if value
            }
            tasks = [
                task
                for task in store.tasks(start_time=start, end_time=end, limit=limit * 2)
                if task.correlation_id in correlations
            ][:limit]
            records = _localize_records(
                sorted(
                    [
                        *_observation_records(observations),
                        *_event_records(events),
                        *_task_records(tasks),
                    ],
                    key=_record_order,
                )[:limit],
                tz_name,
            )
            semantics = _semantics(observations, timezone=tz_name, basis="received_at")
            return SpatialHistoryResult(
                range=_range(start, end, tz_name),
                time_semantics=semantics,
                records=records,
                counts={
                    "observation": len(observations),
                    "event": len(events),
                    "task": len(tasks),
                },
                missing_ranges=_missing_ranges(
                    observations,
                    start,
                    end,
                    expected_interval_seconds,
                    semantics,
                ),
                warnings=_range_warnings(start, end, observations) + ([] if not events else []),
                space_id=space_id,
                space_name=space.name,
                include_descendants=include_descendants,
                descendants=sorted(descendants),
                assignments_in_range=[_assignment_data(row) for row in assignments],
                generated_at=_utc(datetime.now(UTC)),
            )

        return self._run(execute)

    def _entity_history(
        self,
        entity_id: str,
        start_time: datetime,
        end_time: datetime,
        timezone: str,
        attribute: str | None = None,
        expected_interval_seconds: int | None = None,
        limit: int = 500,
    ) -> EntityHistoryResult:
        def execute(store: HistoryStore) -> EntityHistoryResult:
            start, end, tz_name = _validated_range(start_time, end_time, timezone)
            entity = store.entity(entity_id)
            if entity is None:
                raise HistoryNotFoundError("The entity does not exist.")
            observations = store.observations(
                start_time=start,
                end_time=end,
                entity_id=entity_id,
                attribute=attribute,
                limit=limit,
            )
            events = store.events(
                start_time=start,
                end_time=end,
                subject_type="entity",
                subject_id=entity_id,
                limit=limit,
            )
            if not events:
                nearby = store.events(start_time=start - timedelta(minutes=5), limit=limit)
                events = [event for event in nearby if event.subject_id == entity_id]
            correlations = {
                value
                for value in (
                    *[observation.correlation_id for observation in observations],
                    *[event.correlation_id for event in events],
                )
                if value
            }
            tasks = [
                task
                for task in store.tasks(start_time=start, end_time=end, limit=limit)
                if task.correlation_id in correlations
            ]
            records = _localize_records(
                sorted(
                    [
                        *_observation_records(observations),
                        *_event_records(events),
                        *_task_records(tasks),
                    ],
                    key=_record_order,
                )[:limit],
                tz_name,
            )
            semantics = _semantics(observations, timezone=tz_name, basis="received_at")
            return EntityHistoryResult(
                range=_range(start, end, tz_name),
                time_semantics=semantics,
                records=records,
                counts={
                    "observation": len(observations),
                    "event": len(events),
                    "task": len(tasks),
                },
                missing_ranges=_missing_ranges(
                    observations,
                    start,
                    end,
                    expected_interval_seconds,
                    semantics,
                ),
                warnings=_range_warnings(start, end, observations),
                entity_id=entity_id,
                entity_name=entity.name,
                device_id=entity.metadata_summary.get("device_id"),
                space_assignments=[
                    _assignment_data(row) for row in store.entity_assignments(entity_id=entity_id)
                ],
                generated_at=_utc(datetime.now(UTC)),
            )

        return self._run(execute)

    def _trends(
        self,
        start_time: datetime,
        end_time: datetime,
        attribute: str,
        timezone: str,
        group_by: str,
        space_id: str | None = None,
        entity_id: str | None = None,
        include_descendants: bool = True,
        limit: int = 1000,
    ) -> TrendQueryResult:
        if group_by not in {"space", "entity"}:
            raise HistoryValidationError("group_by must be 'space' or 'entity'.")

        def execute(store: HistoryStore) -> TrendQueryResult:
            start, end, tz_name = _validated_range(start_time, end_time, timezone)
            observations = store.observations(
                start_time=start,
                end_time=end,
                space_id=space_id,
                entity_id=entity_id,
                include_descendants=include_descendants,
                attribute=attribute,
                quality_status="valid",
                limit=limit,
            )
            spaces = {space.id: space.name for space in store.spaces()}
            entities = {entity.id: entity.name for entity in store.entities()}
            grouped: dict[str, list[Observation]] = defaultdict(list)
            for observation in observations:
                group_id = observation.space_id if group_by == "space" else observation.entity_id
                if group_id is not None:
                    grouped[group_id].append(observation)
            statistics: list[TrendStatistics] = []
            for group_id, rows in sorted(grouped.items()):
                numeric = [
                    (row, value)
                    for row, value in ((row, _numeric_value(row.normalized_value)) for row in rows)
                    if value is not None
                ]
                if not numeric:
                    continue
                ordered = sorted(numeric, key=lambda item: _observation_time(item[0]))
                values = [value for _, value in ordered]
                first_at = _utc(_observation_time(ordered[0][0]))
                last_at = _utc(_observation_time(ordered[-1][0]))
                elapsed = max((last_at - first_at).total_seconds(), 0.0)
                change = values[-1] - values[0]
                statistics.append(
                    TrendStatistics(
                        group_key=group_id,
                        label=spaces.get(group_id, entities.get(group_id, group_id)),
                        attribute=attribute,
                        observation_count=len(rows),
                        valid_count=len(values),
                        numeric_count=len(values),
                        minimum=min(values),
                        maximum=max(values),
                        average=sum(values) / len(values),
                        first_value=values[0],
                        last_value=values[-1],
                        change=change,
                        change_per_hour=change / (elapsed / 3600) if elapsed else None,
                        first_at=first_at,
                        last_at=last_at,
                        unit=ordered[-1][0].normalized_unit,
                    )
                )
            statistics.sort(
                key=lambda item: item.average if item.average is not None else -math.inf
            )
            semantics = _semantics(observations, timezone=tz_name, basis="received_at")
            return TrendQueryResult(
                range=_range(start, end, tz_name),
                time_semantics=semantics,
                attribute=attribute,
                group_by=group_by,  # type: ignore[arg-type]
                include_descendants=include_descendants,
                statistics=statistics,
                missing_ranges=_missing_ranges(observations, start, end, None, semantics),
                warnings=_range_warnings(start, end, observations),
                generated_at=_utc(datetime.now(UTC)),
            )

        return self._run(execute)

    def _snapshot_at(
        self,
        at_time: datetime,
        timezone: str,
        requested_environment_id: str | None = None,
        nearest: bool = False,
    ) -> SnapshotLookupResult:
        def execute(store: HistoryStore) -> SnapshotLookupResult:
            at = _validated_instant(at_time, timezone)
            tz_name = _timezone_name(timezone)
            if requested_environment_id is None:
                environment = store.default_environment(self._environment_name)
                environment_id = environment.id if environment else None
            else:
                environment_id = requested_environment_id
            if environment_id is None:
                raise HistoryNotFoundError("The default environment does not exist.")
            if nearest:
                snapshot, distance = store.nearest_snapshot(
                    environment_id=environment_id,
                    at_time=at,
                )
                warning = (
                    f"The nearest retained snapshot is {distance} seconds away."
                    if snapshot is not None
                    else "No environment snapshot is retained for this time."
                )
            else:
                snapshot = store.snapshot_at_or_before(
                    environment_id=environment_id,
                    at_time=at,
                )
                distance = (
                    int(abs((at - _utc(snapshot.created_at)).total_seconds()))
                    if snapshot is not None
                    else None
                )
                warning = (
                    "No snapshot at or before the requested time is retained."
                    if snapshot is None
                    else None
                )
            return SnapshotLookupResult(
                requested_at=at,
                snapshot=_snapshot_view(snapshot) if snapshot is not None else None,
                local_requested_at=_local_text(at, tz_name),
                selection="nearest" if nearest else "at_or_before",
                distance_seconds=distance,
                state_as_of=(
                    snapshot.state_generated_at or snapshot.created_at
                    if snapshot is not None
                    else None
                ),
                warning=warning,
            )

        return self._run(execute)

    def _snapshot_diff(
        self,
        baseline_id: str | None,
        target_id: str | None,
        baseline_at: datetime | None,
        target_at: datetime | None,
        timezone: str,
    ) -> SnapshotDiffResult:
        def execute(store: HistoryStore) -> SnapshotDiffResult:
            baseline = self._resolve_snapshot(store, baseline_id, baseline_at, timezone)
            target = self._resolve_snapshot(store, target_id, target_at, timezone)
            if baseline.id == target.id:
                raise HistoryValidationError("The two snapshot selections are the same record.")
            if baseline.environment_id != target.environment_id:
                raise HistoryValidationError("Snapshots must belong to the same environment.")
            before_flat = _flatten_snapshot(baseline.context)
            after_flat = _flatten_snapshot(target.context)
            changes: list[SnapshotDiffEntry] = []
            for path in sorted(before_flat.keys() | after_flat.keys()):
                before = before_flat.get(path)
                after = after_flat.get(path)
                if before == after:
                    continue
                sensor_type = before_flat.get(f"{path.rsplit('/', 1)[0]}/sensor_type")
                recoverability = _recoverability(path, sensor_type)
                changes.append(
                    SnapshotDiffEntry(
                        path=path,
                        before=before,
                        after=after,
                        change_type=(
                            "added" if before is None else "removed" if after is None else "changed"
                        ),
                        recoverability=recoverability,
                        recoverable_by_device=recoverability == "device_command_candidate",
                        physical_rollback_possible=False,
                        explanation=_recoverability_explanation(recoverability, path),
                    )
                )
            return SnapshotDiffResult(
                baseline=_snapshot_view(baseline),
                target=_snapshot_view(target),
                changes=changes,
                unchanged_count=len(before_flat.keys() & after_flat.keys()) - len(changes),
                device_recoverable_paths=[
                    change.path for change in changes if change.recoverable_by_device
                ],
                physical_change_paths=[
                    change.path
                    for change in changes
                    if change.recoverability == "physical_observation"
                ],
                missing_data_paths=[
                    change.path
                    for change in changes
                    if change.before is None or change.after is None
                ],
                reality_git={
                    "comparison": "Stored snapshots are compared at their recorded times.",
                    "rollback": "Device commands may restore selected projections; "
                    "physical conditions cannot be truly rolled back.",
                },
                generated_at=_utc(datetime.now(UTC)),
            )

        return self._run(execute)

    def _correlate(
        self,
        record_type: str,
        record_id: str,
        timezone: str,
    ) -> CorrelatedHistory:
        def execute(store: HistoryStore) -> CorrelatedHistory:
            tz_name = _timezone_name(timezone)
            if record_type == "observation":
                row = store.observation(record_id)
                if row is None:
                    raise HistoryNotFoundError("The observation does not exist.")
                record = _observation_records([row])[0]
                at = _observation_time(row)
                observations = [row]
                events = self._related_events(
                    store,
                    record.correlation_id,
                    row.entity_id,
                    at,
                )
            elif record_type == "event":
                row = store.event(record_id)
                if row is None:
                    raise HistoryNotFoundError("The event does not exist.")
                record = _event_records([row])[0]
                at = _utc(row.occurred_at)
                observations = self._related_observations(
                    store,
                    row.correlation_id,
                    row.subject_id,
                    at,
                )
                events = [row]
            elif record_type == "task":
                row = store.task(record_id)
                if row is None:
                    raise HistoryNotFoundError("The task does not exist.")
                record = _task_records([row])[0]
                at = _utc(row.created_at)
                end = _utc(row.completed_at or row.created_at + timedelta(hours=1))
                events = [
                    event
                    for event in store.events(
                        start_time=at - timedelta(minutes=5),
                        end_time=end + timedelta(minutes=5),
                        limit=1000,
                    )
                    if event.correlation_id and event.correlation_id == row.correlation_id
                ]
                observations = store.observations(
                    start_time=at,
                    end_time=end,
                    limit=1000,
                )
                if row.correlation_id:
                    observations = [
                        item for item in observations if item.correlation_id == row.correlation_id
                    ]
            else:
                raise HistoryValidationError("record_type must be observation, event, or task.")
            correlations = {record.correlation_id} if record.correlation_id else set()
            tasks = [
                task
                for task in store.tasks(start_time=at - timedelta(hours=1), limit=1000)
                if task.correlation_id in correlations
            ]
            environment = store.default_environment(self._environment_name)
            snapshots = (
                [
                    _snapshot_view(snapshot)
                    for snapshot in store.snapshots_around(
                        environment_id=environment.id,
                        at_time=at,
                        limit=1,
                    )
                ]
                if environment is not None
                else []
            )
            return CorrelatedHistory(
                record=record,
                events=_localize_records(
                    [*(_event_records(events) if record_type != "event" else [record])],
                    tz_name,
                ),
                tasks=_localize_records(_task_records(tasks), tz_name),
                observations=_localize_records(_observation_records(observations), tz_name),
                snapshots=snapshots,
                relation_basis={
                    "events": "correlation_id or matching subject within five minutes",
                    "tasks": "correlation_id",
                    "observations": "correlation_id, matching subject, or task time window",
                    "snapshots": "nearest retained snapshot",
                },
                warnings=[
                    "Relations without a shared correlation_id are inferred "
                    "and are not authoritative."
                ],
            )

        return self._run(execute)

    def _ask(self, query: str, timezone: str, now: datetime | None) -> NaturalHistoryAnswer:
        parsed = self._run(lambda store: self._parse_query(store, query, timezone, now))
        if parsed is None:
            raise HistoryQueryUnsupportedError(
                "Only the deterministic environmental-history query patterns are supported."
            )
        interpretation, start, end, now_utc = parsed
        return self._execute_natural(
            query,
            interpretation,
            start,
            end,
            timezone,
            now_utc,
        )

    def _parse_query(
        self,
        store: HistoryStore,
        query: str,
        timezone: str,
        now: datetime | None,
    ) -> tuple[NaturalHistoryInterpretation, datetime, datetime, datetime] | None:
        text_value = query.strip()
        if not text_value:
            raise HistoryValidationError("The query cannot be blank.")
        now_utc = _utc(now) if now is not None else _utc(datetime.now(UTC))
        tz_name = _timezone_name(timezone)
        local_now = now_utc.astimezone(ZoneInfo(tz_name))
        local_date = local_now.date()
        start_local = datetime.combine(local_date, time.min, local_now.tzinfo)
        end_local = start_local + timedelta(days=1)
        ranking = "哪个房间" in text_value and ("最" in text_value)
        trend = "变化" in text_value and ("之后" in text_value or "温度" in text_value)
        running = "还在运行" in text_value or "哪些设备" in text_value
        events_question = "发生了什么" in text_value or "发生了" in text_value
        if ranking:
            start_local -= timedelta(days=7)
            end_local = local_now.replace(microsecond=0)
            attribute = "humidity" if "湿" in text_value else _attribute_from_text(text_value)
            if attribute is None:
                return None
            return (
                NaturalHistoryInterpretation(
                    question_type="space_ranking",
                    confidence=0.8,
                    explanation=(
                        "Ranked retained observations by space using a deterministic parser."
                    ),
                    attribute=attribute,
                ),
                _utc(start_local),
                _utc(end_local),
                now_utc,
            )
        if "昨天" in text_value:
            start_local -= timedelta(days=1)
            end_local -= timedelta(days=1)
        if "今天" in text_value:
            end_local = min(end_local, local_now.replace(microsecond=0))
        if "下午" in text_value:
            start_local = datetime.combine(
                start_local.date(),
                time(hour=12),
                start_local.tzinfo,
            )
            end_local = datetime.combine(
                start_local.date(),
                time(hour=18),
                start_local.tzinfo,
            )
        elif "晚上" in text_value:
            start_local = datetime.combine(
                start_local.date(),
                time(hour=18),
                start_local.tzinfo,
            )
            end_local = start_local + timedelta(hours=6)
        elif "上午" in text_value:
            start_local = datetime.combine(
                start_local.date(),
                time(hour=6),
                start_local.tzinfo,
            )
            end_local = datetime.combine(
                start_local.date(),
                time(hour=12),
                start_local.tzinfo,
            )
        action = None
        if any(word in text_value for word in ("关闭", "关掉", "关上")):
            action = "off"
        elif any(word in text_value for word in ("打开", "开启")):
            action = "on"
        entity = self._resolve_named_entity(store, "空调", text_value)
        attribute = _attribute_from_text(text_value)
        if trend and entity is not None and attribute is not None:
            return (
                NaturalHistoryInterpretation(
                    question_type="entity_attribute_trend",
                    confidence=0.7,
                    explanation="Resolved a local time range, a named entity, and an attribute.",
                    action=action,
                    entity_id=entity.id,
                    attribute=attribute,
                ),
                _utc(start_local),
                _utc(end_local),
                now_utc,
            )
        if running and ("晚上" in text_value or "离开" in text_value):
            return (
                NaturalHistoryInterpretation(
                    question_type="running_devices",
                    confidence=0.7,
                    explanation="Used the nearest retained snapshot at the resolved local time.",
                    action=action,
                ),
                _utc(start_local),
                _utc(end_local),
                now_utc,
            )
        if events_question:
            space = self._resolve_named_space(store, text_value)
            if space is None:
                return (
                    NaturalHistoryInterpretation(
                        question_type="events_in_space",
                        confidence=0.4,
                        explanation="Time range was resolved, but no known space matched.",
                    ),
                    _utc(start_local),
                    _utc(end_local),
                    now_utc,
                )
            return (
                NaturalHistoryInterpretation(
                    question_type="events_in_space",
                    confidence=0.8,
                    explanation="Resolved the local day and a known space.",
                    space_id=space.id,
                ),
                _utc(start_local),
                _utc(end_local),
                now_utc,
            )
        return None

    def _execute_natural(
        self,
        query: str,
        interpretation: NaturalHistoryInterpretation,
        start: datetime,
        end: datetime,
        timezone: str,
        now_utc: datetime,
    ) -> NaturalHistoryAnswer:
        tz_name = _timezone_name(timezone)
        result_range = _range(start, end, tz_name)
        records: list[HistoryRecord] = []
        statistics: list[TrendStatistics] = []
        snapshots: list[EnvironmentSnapshotView] = []
        missing: list[TimeGap] = []
        warnings: list[str] = []
        if interpretation.question_type == "events_in_space" and interpretation.space_id:
            result = self._spatial_history(
                interpretation.space_id,
                start_time=start,
                end_time=end,
                timezone=timezone,
                limit=100,
            )
            records = result.records
            missing = result.missing_ranges
            warnings.extend(result.warnings)
            if not records:
                answer = (
                    f"查询范围 {_local_text(start, tz_name)} 到 {_local_text(end, tz_name)} "
                    "没有可用的保留记录；不能据此判断现实中没有发生任何事情。"
                )
            else:
                preview = "; ".join(_record_preview(record) for record in records[:3])
                answer = f"该范围内共有 {len(records)} 条记录：{preview}。"
        elif interpretation.question_type == "space_ranking" and interpretation.attribute:
            result = self._trends(
                start_time=start,
                end_time=end,
                attribute=interpretation.attribute,
                timezone=timezone,
                group_by="space",
                limit=1000,
            )
            statistics = result.statistics
            records = _localize_records(
                [
                    HistoryRecord(
                        record_type="observation",
                        record_id=f"aggregate:{item.group_key}",
                        occurred_at=item.last_at,
                        data=item.model_dump(mode="json"),
                    )
                    for item in statistics
                ],
                tz_name,
            )
            missing = result.missing_ranges
            warnings.extend(result.warnings)
            if not statistics:
                answer = (
                    f"过去七天内没有可比较的有效 {interpretation.attribute} 数值记录，"
                    "无法判断哪个房间最潮湿。"
                )
            else:
                best = max(statistics, key=lambda item: item.average or -math.inf)
                answer = (
                    f"在保留的有效记录中，{best.label} 的平均 {best.attribute} 最高："
                    f"{best.average:.2f}{best.unit or ''}（{best.valid_count} 条）。"
                )
        elif (
            interpretation.question_type == "entity_attribute_trend"
            and interpretation.entity_id
            and interpretation.attribute
        ):
            result = self._entity_history(
                interpretation.entity_id,
                start_time=start,
                end_time=end,
                timezone=timezone,
                limit=1000,
            )
            if interpretation.action:
                candidates = []
                for event in result.records:
                    if event.record_type != "event":
                        continue
                    payload = event.data.get("payload", {})
                    joined = str(payload).casefold()
                    if interpretation.action in joined and (
                        event.entity_id == interpretation.entity_id
                        or event.subject_id == interpretation.entity_id
                    ):
                        candidates.append(event)
                if candidates:
                    action_event = candidates[-1]
                    # Keep a short pre-action baseline so "what changed after?" has a before value.
                    start = _utc(action_event.occurred_at or start) - timedelta(minutes=10)
                    result = self._entity_history(
                        interpretation.entity_id,
                        start_time=start,
                        end_time=end,
                        timezone=timezone,
                        attribute=interpretation.attribute,
                        limit=1000,
                    )
                    interpretation.action_resolved = True
                else:
                    warnings.append("没有找到明确的设备动作事件；以下统计仍覆盖原查询范围。")
            observations = [row for row in result.records if row.record_type == "observation"]
            values = [
                value
                for value in (_numeric_record_value(row) for row in observations)
                if value is not None
            ]
            if not values:
                answer = f"在可用记录中没有 {interpretation.attribute} 数值，无法回答变化。"
            else:
                change = values[-1] - values[0]
                answer = (
                    f"记录显示 {interpretation.attribute} 从 {values[0]:.2f} 变为 "
                    f"{values[-1]:.2f}，变化 {change:+.2f}。"
                )
            records = result.records
            missing = result.missing_ranges
            warnings.extend(result.warnings)
        elif interpretation.question_type == "running_devices":
            snapshot_result = self._snapshot_at(
                at_time=end,
                timezone=timezone,
                nearest=False,
            )
            snapshot = snapshot_result.snapshot
            if snapshot is None:
                answer = "该时间点没有保留的环境快照，无法基于记录判断哪些设备仍在运行。"
                warnings.append("缺少请求时间之前的环境快照。")
            else:
                snapshots.append(snapshot)
                running = _running_from_snapshot(snapshot.context)
                if not running:
                    answer = "最近的保留快照中没有可解释为正在运行的设备状态。"
                else:
                    answer = "最近快照显示运行中的设备：" + "; ".join(running) + "。"
        else:
            answer = "这个问题超出了当前确定性历史查询模板，无法给出基于记录的回答。"
            warnings.append("The query was not supported.")
        return NaturalHistoryAnswer(
            query=query,
            interpretation=interpretation,
            range=result_range,
            time_semantics=TimeSemantics(
                local_timezone=tz_name,
                query_time_basis="received_at",
                observations_without_collected_time=[
                    record.record_id
                    for record in records
                    if record.record_type == "observation" and record.collected_at is None
                ],
            ),
            answer=answer,
            based_on_record_count=len(records),
            records=records[:100],
            statistics=statistics,
            snapshots=snapshots,
            missing_ranges=missing,
            warnings=warnings,
            generated_at=now_utc,
        )

    def _resolve_named_space(self, store: HistoryStore, query: str) -> Any | None:
        aliases = _space_aliases(query)
        spaces = store.spaces()
        for alias in aliases:
            exact = store.find_space_by_name(alias)
            if exact is not None:
                return exact
        lowered = query.casefold()
        for space in spaces:
            if space.name.casefold() in lowered or any(
                alias.casefold() in space.name.casefold() for alias in aliases
            ):
                return space
        return None

    def _resolve_named_entity(
        self,
        store: HistoryStore,
        default_name: str,
        query: str,
    ) -> Any | None:
        aliases = _entity_aliases(query) or [default_name]
        entities = store.entities()
        for alias in aliases:
            exact = store.find_entity_by_name(alias)
            if exact is not None:
                return exact
        lowered = query.casefold()
        for entity in entities:
            if entity.name.casefold() in lowered:
                return entity
        tags = {"空调": "climate", "灯": "light"}
        for alias, tag in tags.items():
            if alias in query:
                return next((entity for entity in entities if tag in entity.semantic_tags), None)
        return None

    def _resolve_snapshot(
        self,
        store: HistoryStore,
        snapshot_id: str | None,
        at_time: datetime | None,
        timezone: str,
    ) -> EnvironmentSnapshot:
        if snapshot_id is not None:
            snapshot = store.snapshot(snapshot_id)
            if snapshot is None:
                raise HistoryNotFoundError("The snapshot does not exist.")
            return snapshot
        if at_time is None:
            raise HistoryValidationError("Provide snapshot_id or at_time for each side.")
        at = _validated_instant(at_time, timezone)
        environment = store.default_environment(self._environment_name)
        if environment is None:
            raise HistoryNotFoundError("The default environment does not exist.")
        snapshot = store.snapshot_at_or_before(
            environment_id=environment.id,
            at_time=at,
        )
        if snapshot is None:
            raise HistoryNotFoundError("No snapshot at or before the requested time exists.")
        return snapshot

    def _related_events(
        self,
        store: HistoryStore,
        correlation_id: str | None,
        entity_id: str | None,
        at: datetime,
    ) -> list[Event]:
        candidates = store.events(
            start_time=at - timedelta(minutes=5),
            end_time=at + timedelta(minutes=5),
            limit=1000,
        )
        return [
            event
            for event in candidates
            if (correlation_id and event.correlation_id == correlation_id)
            or (entity_id and event.subject_id == entity_id)
        ]

    def _related_observations(
        self,
        store: HistoryStore,
        correlation_id: str | None,
        subject_id: str | None,
        at: datetime,
    ) -> list[Observation]:
        candidates = store.observations(
            start_time=at - timedelta(minutes=5),
            end_time=at + timedelta(minutes=5),
            limit=1000,
        )
        return [
            observation
            for observation in candidates
            if (correlation_id and observation.correlation_id == correlation_id)
            or (subject_id and observation.entity_id == subject_id)
        ]

    def _run(self, function: Callable[[HistoryStore], Any]) -> Any:
        with self._unit_of_work_factory() as unit_of_work:
            if unit_of_work.history is None:
                raise RuntimeError("The history repository is unavailable.")
            return function(SqlAlchemyHistoryStore(unit_of_work.history))


def _validated_range(
    start_time: datetime,
    end_time: datetime,
    timezone: str,
) -> tuple[datetime, datetime, str]:
    start = _validated_instant(start_time, timezone)
    end = _validated_instant(end_time, timezone)
    if end <= start:
        raise HistoryValidationError("end_time must be after start_time.")
    if end - start > timedelta(days=MAX_RANGE_DAYS):
        raise HistoryValidationError("The requested history range is too large.")
    return start, end, _timezone_name(timezone)


def _validated_instant(value: datetime, timezone: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HistoryValidationError("Times must include an explicit UTC offset.")
    return _utc(value)


def _timezone_name(timezone: str) -> str:
    try:
        ZoneInfo(timezone)
    except Exception as exc:
        raise HistoryValidationError("The requested timezone is not supported.") from exc
    return timezone


def _range(start: datetime, end: datetime, timezone: str) -> HistoryTimeRange:
    return HistoryTimeRange(
        start_time=start,
        end_time=end,
        local_start_time=_local_text(start, timezone),
        local_end_time=_local_text(end, timezone),
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _local_text(value: datetime, timezone: str) -> str:
    return _utc(value).astimezone(ZoneInfo(timezone)).isoformat()


def _localize_records(records: list[HistoryRecord], timezone: str) -> list[HistoryRecord]:
    return [
        record.model_copy(
            update={
                "local_time": _local_text(
                    record.collected_at
                    or record.occurred_at
                    or record.received_at
                    or record.processed_at
                    or datetime.min.replace(tzinfo=UTC),
                    timezone,
                )
            }
        )
        for record in records
    ]


def _observation_time(value: Observation) -> datetime:
    return _utc(value.observed_at or value.received_at)


def _record_order(value: HistoryRecord) -> tuple[datetime, str, str]:
    moment = value.collected_at or value.occurred_at or value.received_at or value.processed_at
    if moment is None:
        moment = datetime.max.replace(tzinfo=UTC)
    return moment, value.record_type, value.record_id


def _observation_records(rows: list[Observation]) -> list[HistoryRecord]:
    return [
        HistoryRecord(
            record_type="observation",
            record_id=row.observation_id,
            collected_at=_utc(row.observed_at) if row.observed_at else None,
            received_at=_utc(row.received_at),
            processed_at=_utc(row.processed_at) if row.processed_at else None,
            local_time=None,
            source=f"{row.source_type}:{row.source_id}",
            entity_id=row.entity_id,
            space_id=row.space_id,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            attribute=row.attribute,
            value=row.normalized_value,
            unit=row.normalized_unit,
            quality_status=row.quality_status,
            correlation_id=row.correlation_id,
            data={
                "raw_value": None,
                "observed_at_source": row.observed_at_source,
                "observed_at_uncertainty_ms": row.observed_at_uncertainty_ms,
                "quality_issues": row.quality_issues,
                "valid_from": _utc(row.valid_from) if row.valid_from else None,
                "valid_until": _utc(row.valid_until) if row.valid_until else None,
            },
        )
        for row in rows
    ]


def _event_records(rows: list[Event]) -> list[HistoryRecord]:
    return [
        HistoryRecord(
            record_type="event",
            record_id=row.id,
            occurred_at=_utc(row.occurred_at),
            received_at=_utc(row.created_at),
            processed_at=_utc(row.created_at),
            local_time=None,
            source=row.source,
            subject_type=row.subject_type,
            subject_id=row.subject_id,
            correlation_id=row.correlation_id,
            data={"event_type": row.event_type, "payload": row.payload},
        )
        for row in rows
    ]


def _task_records(rows: list[Task]) -> list[HistoryRecord]:
    return [
        HistoryRecord(
            record_type="task",
            record_id=row.id,
            occurred_at=_utc(row.created_at),
            received_at=_utc(row.started_at) if row.started_at else None,
            processed_at=_utc(row.completed_at) if row.completed_at else None,
            local_time=None,
            source=row.origin,
            correlation_id=row.correlation_id,
            data={
                "task_type": row.task_type,
                "title": row.title,
                "status": row.status,
                "result": row.result,
                "error": row.error,
            },
        )
        for row in rows
    ]


def _snapshot_view(row: EnvironmentSnapshot) -> EnvironmentSnapshotView:
    return EnvironmentSnapshotView(
        id=row.id,
        environment_id=row.environment_id,
        context=row.context,
        active_task_ids=row.active_task_ids,
        anomaly_count=row.anomaly_count,
        context_version=row.context_version,
        state_generated_at=_utc(row.state_generated_at) if row.state_generated_at else None,
        created_at=_utc(row.created_at),
        local_created_at=_local_text(row.created_at, "UTC"),
    )


def _assignment_data(row: EntitySpaceAssignment) -> dict[str, Any]:
    return {
        "entity_id": row.entity_id,
        "space_id": row.space_id,
        "valid_from": _utc(row.valid_from).isoformat(),
        "valid_until": _utc(row.valid_until).isoformat() if row.valid_until else None,
        "source_type": row.source_type,
        "confidence": row.confidence,
    }


def _semantics(
    observations: list[Observation],
    *,
    timezone: str,
    basis: QueryTimeBasis,
) -> TimeSemantics:
    late: list[str] = []
    future: list[str] = []
    missing_collected: list[str] = []
    for row in observations:
        if row.observed_at is None:
            missing_collected.append(row.observation_id)
            continue
        collected = _utc(row.observed_at)
        delay = (_utc(row.received_at) - collected).total_seconds()
        if delay > 60:
            late.append(row.observation_id)
        if delay < -30:
            future.append(row.observation_id)
    return TimeSemantics(
        local_timezone=timezone,
        query_time_basis=basis,
        collected_time_available=sum(row.observed_at is not None for row in observations),
        received_time_available=len(observations),
        processed_time_available=sum(row.processed_at is not None for row in observations),
        late_observations=late,
        future_clock_skew_observations=future,
        observations_without_collected_time=missing_collected,
        late_arrival_threshold_seconds=60,
        clock_skew_tolerance_seconds=30,
    )


def _missing_ranges(
    observations: list[Observation],
    start: datetime,
    end: datetime,
    expected_interval_seconds: int | None,
    semantics: TimeSemantics,
) -> list[TimeGap]:
    if not observations:
        return [
            TimeGap(
                start_time=start,
                end_time=end,
                duration_seconds=int((end - start).total_seconds()),
                reason="No retained observation was selected for this query range.",
            )
        ]
    if expected_interval_seconds is None or expected_interval_seconds <= 0:
        if semantics.observations_without_collected_time:
            return [
                TimeGap(
                    start_time=start,
                    end_time=end,
                    duration_seconds=int((end - start).total_seconds()),
                    reason=(
                        "Coverage is unknown because collected time is missing for some records."
                    ),
                )
            ]
        return []
    threshold = expected_interval_seconds * 2.5
    ordered = sorted({_observation_time(row) for row in observations})
    bounds = [start, *ordered, end]
    gaps: list[TimeGap] = []
    for left, right in zip(bounds, bounds[1:], strict=False):
        duration = (right - left).total_seconds()
        if duration > threshold:
            gaps.append(
                TimeGap(
                    start_time=left,
                    end_time=right,
                    duration_seconds=int(duration),
                    reason="No retained observation within the expected sampling interval window.",
                )
            )
    return gaps


def _range_warnings(
    start: datetime,
    end: datetime,
    observations: list[Observation],
) -> list[str]:
    warnings = [
        "Observations are selected by received_at so late-arriving records remain visible; "
        "events and tasks use their native occurrence/creation time."
    ]
    if not observations:
        warnings.append(
            f"No observation is retained between {_local_text(start, 'UTC')} and "
            f"{_local_text(end, 'UTC')}."
        )
    return warnings


def _numeric_value(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _numeric_record_value(record: HistoryRecord) -> float | None:
    return _numeric_value(record.value)


def _flatten_snapshot(context: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "devices" in context or "sensors" in context:
        for device_id, device in context.get("devices", {}).items():
            result[f"/devices/{device_id}/name"] = device.get("name")
            result[f"/devices/{device_id}/area"] = device.get("area")
            result[f"/devices/{device_id}/state"] = device.get("state")
            for key, value in device.get("attributes", {}).items():
                result[f"/devices/{device_id}/attributes/{key}"] = value
        for sensor_id, sensor in context.get("sensors", {}).items():
            for key in ("sensor_type", "value", "unit"):
                result[f"/sensors/{sensor_id}/{key}"] = sensor.get(key)
        return result

    def walk(spaces: list[dict[str, Any]], prefix: str) -> None:
        for space in spaces:
            space_id = space.get("space_id", "")
            base = f"{prefix}/spaces/{space_id}"
            for attribute, state in space.get("states", {}).items():
                result[f"{base}/state/{attribute}"] = _comparable_state(state)
            for entity in space.get("entities", []):
                entity_id = entity.get("entity_id", "")
                entity_base = f"{base}/entities/{entity_id}"
                for attribute, state in entity.get("states", {}).items():
                    result[f"{entity_base}/state/{attribute}"] = _comparable_state(state)
            walk(space.get("children", []), base)

    walk(context.get("spaces", []), "")
    result["/quality"] = context.get("quality")
    return result


def _comparable_state(state: dict[str, Any]) -> dict[str, Any]:
    excluded = {
        "id",
        "target_id",
        "environment_id",
        "input_cutoff_at",
        "effective_from",
        "generated_at",
        "valid_until",
        "superseded_at",
        "created_at",
        "rule",
        "evidence_summary",
    }
    return {key: value for key, value in state.items() if key not in excluded}


def _recoverability(path: str, sensor_type: object | None = None) -> str:
    if path.startswith("/devices/") and (path.endswith("/state") or "/attributes/" in path):
        return "device_command_candidate"
    if (
        path.startswith("/sensors/")
        and path.endswith("/value")
        and str(sensor_type) in PHYSICAL_ATTRIBUTES
    ):
        return "physical_observation"
    if any(path.endswith(f"/state/{attribute}") for attribute in DEVICE_COMMAND_ATTRIBUTES):
        return "device_command_candidate"
    if any(path.endswith(f"/state/{attribute}") for attribute in PHYSICAL_ATTRIBUTES):
        return "physical_observation"
    if path == "/quality" or "/state/status" in path or path.endswith("/unit"):
        return "system_projection"
    return "unknown"


def _recoverability_explanation(recoverability: str, path: str) -> str:
    explanations = {
        "device_command_candidate": (
            "This projection looks device-command related; recovery still requires a new, "
            "verified action and cannot use this diff as time travel."
        ),
        "physical_observation": (
            "This is an observed physical condition; the system may actuate toward it, "
            "but the past physical state cannot truly be rolled back."
        ),
        "system_projection": "This is a system-derived projection or diagnostic value.",
        "metadata_only": "This is snapshot metadata and not a physical state rollback target.",
        "unknown": "Recoverability cannot be determined from the retained projection.",
    }
    return explanations.get(recoverability, f"Cannot classify {path}.")


def _attribute_from_text(value: str) -> str | None:
    if "湿" in value:
        return "humidity"
    if "温度" in value:
        return "temperature"
    if "光照" in value or "亮度" in value:
        return "illuminance"
    if "人" in value or "占用" in value:
        return "occupancy"
    return None


def _space_aliases(query: str) -> list[str]:
    table = {
        "客厅": ["living room", "living space", "客厅"],
        "起居室": ["living room", "living space"],
        "卧室": ["bedroom", "sleep"],
        "厨房": ["kitchen"],
        "书房": ["study", "office"],
        "餐厅": ["dining"],
        "卫生间": ["bathroom", "toilet"],
        "浴室": ["bathroom"],
        "家": ["home"],
    }
    aliases: list[str] = []
    for token, values in table.items():
        if token in query:
            aliases.extend(values)
    return aliases or [query]


def _entity_aliases(query: str) -> list[str]:
    table = {
        "空调": ["air conditioner", "climate", "ac"],
        "灯": ["light", "lamp"],
    }
    aliases: list[str] = []
    for token, values in table.items():
        if token in query:
            aliases.extend(values)
    return aliases


def _record_preview(record: HistoryRecord) -> str:
    moment = record.collected_at or record.occurred_at or record.received_at
    label = record.attribute or record.data.get("event_type") or record.data.get("title")
    return f"{moment.isoformat()} {label or record.record_type}"


def _running_from_snapshot(context: dict[str, Any]) -> list[str]:
    running: list[str] = []
    off_states = {"off", "unavailable", "unknown", "standby"}
    for device in context.get("devices", {}).values():
        state = str(device.get("state", "")).casefold()
        if state and state not in off_states:
            running.append(f"{device.get('name', 'device')}={state}")
    for space in context.get("spaces", []):
        for entity in space.get("entities", []):
            for attribute, state in entity.get("states", {}).items():
                value = state.get("value")
                if attribute in {"power", "occupancy", "motion"} and value in (True, "on", "open"):
                    running.append(f"{entity.get('name', entity.get('entity_id'))}={value}")
    return sorted(set(running))


__all__ = ["HistoryService"]
