import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "nova_core"


def imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".", 1)[0])
    return modules


def test_database_dependencies_stay_inside_persistence_boundary() -> None:
    python_files = list(PACKAGE_ROOT.rglob("*.py"))

    assert python_files
    for path in python_files:
        modules = imported_modules(path.read_text(encoding="utf-8"))
        inside_persistence = path.relative_to(PACKAGE_ROOT).parts[0] == "persistence"

        if inside_persistence:
            continue
        assert "sqlalchemy" not in modules, f"{path} imports SQLAlchemy outside persistence"
        assert "alembic" not in modules, f"{path} imports Alembic outside persistence"


def test_later_phase_modules_are_not_implemented_yet() -> None:
    forbidden_directories = ("adapters", "agents")
    allowed_httpx_file = Path("devices") / "home_assistant.py"

    for path in PACKAGE_ROOT.rglob("*.py"):
        relative = path.relative_to(PACKAGE_ROOT)
        assert relative.parts[0] not in forbidden_directories, f"Unexpected module: {path}"

        modules = imported_modules(path.read_text(encoding="utf-8"))
        if relative == allowed_httpx_file:
            modules.discard("httpx")
        assert "homeassistant" not in modules, f"{path} imports Home Assistant directly"


def test_tool_system_stays_behind_device_and_persistence_ports() -> None:
    tools_root = PACKAGE_ROOT / "tools"
    for path in tools_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        modules = imported_modules(source)
        assert "httpx" not in modules, f"{path} imports HTTP directly"
        assert "sqlalchemy" not in modules, f"{path} imports SQLAlchemy directly"
        assert "nova_core.devices.home_assistant" not in source
        assert "nova_core.persistence" not in source


def test_task_system_uses_tool_executor_and_persistence_ports() -> None:
    tasks_root = PACKAGE_ROOT / "tasks"
    assert list(tasks_root.rglob("*.py"))
    for path in tasks_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        modules = imported_modules(source)
        assert "httpx" not in modules, f"{path} imports HTTP directly"
        assert "sqlalchemy" not in modules, f"{path} imports SQLAlchemy directly"
        assert "homeassistant" not in modules, f"{path} imports Home Assistant directly"
        assert "nova_core.devices" not in source, f"{path} imports a device adapter directly"
        assert "nova_core.persistence" not in source, f"{path} imports persistence directly"


def test_task_steps_call_the_tool_executor_port() -> None:
    source = (PACKAGE_ROOT / "tasks" / "service.py").read_text(encoding="utf-8")
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "execute"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "_tool_executor"
        and isinstance(node.func.value.value, ast.Name)
        and node.func.value.value.id == "self"
    ]
    assert calls


def test_agent_runtime_stays_behind_provider_task_and_catalog_ports() -> None:
    agent_root = PACKAGE_ROOT / "agent_runtime"
    assert list(agent_root.rglob("*.py"))
    for path in agent_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        modules = imported_modules(source)
        assert "httpx" not in modules, f"{path} imports HTTP directly"
        assert "sqlalchemy" not in modules, f"{path} imports SQLAlchemy directly"
        assert "alembic" not in modules, f"{path} imports Alembic directly"
        assert "homeassistant" not in modules, f"{path} imports Home Assistant directly"
        assert "nova_core.persistence" not in source, f"{path} imports persistence directly"
        assert "nova_core.devices" not in source, f"{path} imports a device adapter directly"
        assert "nova_core.tools.executor" not in source, f"{path} imports Tool Executor directly"
        assert "nova_core.ai.openai_compatible" not in source, f"{path} imports a provider directly"


def test_ai_provider_stays_behind_http_and_logging_ports() -> None:
    ai_root = PACKAGE_ROOT / "ai"
    assert list(ai_root.rglob("*.py"))
    for path in ai_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        modules = imported_modules(source)
        assert "sqlalchemy" not in modules, f"{path} imports SQLAlchemy directly"
        assert "alembic" not in modules, f"{path} imports Alembic directly"
        assert "homeassistant" not in modules, f"{path} imports Home Assistant directly"
        assert "nova_core.persistence" not in source, f"{path} imports persistence directly"
        assert "nova_core.devices" not in source, f"{path} imports a device adapter directly"
        assert "nova_core.tasks" not in source, f"{path} imports task state directly"
        if path.name != "openai_compatible.py":
            assert "httpx" not in modules, f"{path} imports HTTP directly"


def test_task_system_does_not_depend_on_ai_or_agent_runtime() -> None:
    tasks_root = PACKAGE_ROOT / "tasks"
    for path in tasks_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "nova_core.ai" not in source, f"{path} imports the AI layer directly"
        assert "nova_core.agent_runtime" not in source, f"{path} imports Agent Runtime directly"
