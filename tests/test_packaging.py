from pathlib import Path
import tomllib


def test_install_system_deps_script_is_packaged():
    project_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads(
        project_root.joinpath("pyproject.toml").read_text(encoding="utf-8")
    )

    package_data = pyproject["tool"]["setuptools"]["package-data"]["bt_record"]

    assert "scripts/*.sh" in package_data
    assert project_root.joinpath("bt_record/scripts/install-system-deps.sh").is_file()
