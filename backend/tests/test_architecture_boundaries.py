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
