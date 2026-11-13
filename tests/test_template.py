import ast
import pathlib
import re
import shutil
import tomllib

import copier
import pytest
import yaml

TEMPLATE = pathlib.Path(__file__).resolve().parent.parent
TEXT_SUFFIXES = {
    ".py",
    ".toml",
    ".yml",
    ".yaml",
    ".md",
    ".rst",
    ".sh",
    ".lua",
    ".json",
    ".mod",
    ".qrc",
    ".cfg",
    "",
}


def generate(tmp_path, **data):
    """Generate a project from a copy of the template, without running its tasks."""
    template = tmp_path / "template_copy"
    template.mkdir(parents=True)
    shutil.copy(TEMPLATE / "copier.yml", template / "copier.yml")
    shutil.copytree(TEMPLATE / "template", template / "template")
    project = tmp_path / "project"
    data.setdefault("project_name", "Demo Project")
    data.setdefault("package_name", "demo_pkg")
    copier.run_copy(
        str(template), project, data=data, defaults=True, skip_tasks=True, quiet=True
    )
    return project


def makefile_modules(project):
    """The shared makefile modules the generated Makefile includes."""
    text = (project / "Makefile").read_text()
    return re.search(r"^MAKEFILES_MODULES = (.*)$", text, re.MULTILINE).group(1).split()


def files(project):
    return {p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file()}


def check_well_formed(project):
    """Everything was rendered, and what should parse does."""
    for path in project.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"\{\{|\{%", text), (
            f"unrendered Jinja in {path.relative_to(project)}"
        )
        if path.suffix == ".py":
            ast.parse(text)
        elif path.suffix in {".yml", ".yaml"}:
            yaml.safe_load(text)
        elif path.suffix == ".toml":
            tomllib.loads(text)


def answers(project):
    return yaml.safe_load((project / ".copier-answers.yml").read_text())


def test_answers_file_is_written_for_updates(tmp_path):
    project = generate(tmp_path)

    saved = answers(project)

    assert saved["_src_path"]
    assert saved["project_name"] == "Demo Project"
    assert saved["package_slug"] == "demo_pkg"


def test_project_name_and_version_are_used(tmp_path):
    project = generate(tmp_path, project_name="My Cool Tool", initial_version="1.2.3")

    pyproject = tomllib.loads((project / "pyproject.toml").read_text())

    assert pyproject["project"]["name"] == "my-cool-tool"
    assert pyproject["project"]["version"] == "1.2.3"
    assert (project / "VERSION").read_text().strip() == "1.2.3"


@pytest.mark.parametrize("package_name", ["my-package", "1abc"])
def test_a_package_name_that_is_not_an_identifier_is_refused(tmp_path, package_name):
    with pytest.raises(ValueError):
        generate(tmp_path, package_name=package_name)


def test_github_workflows_are_optional(tmp_path):
    with_ci = generate(tmp_path / "a")
    without = generate(tmp_path / "b", github_workflow=False)

    assert ".github/workflows/unit_tests.yml" in files(with_ci)
    assert not any(name.startswith(".github") for name in files(without))


def test_dependabot_follows_the_workflows_and_the_develop_branch(tmp_path):
    with_ci = generate(tmp_path / "a", develop_branch="dev")
    without = generate(tmp_path / "b", github_workflow=False)

    config = yaml.safe_load((with_ci / ".github/dependabot.yml").read_text())

    assert {u["package-ecosystem"] for u in config["updates"]} == {
        "uv",
        "github-actions",
    }
    assert {u["target-branch"] for u in config["updates"]} == {"dev"}
    assert ".github/dependabot.yml" not in files(without)


def test_python_version_pin_is_optional(tmp_path):
    pinned = generate(tmp_path / "a", python_version="3.13")
    unpinned = generate(tmp_path / "b", pin_python_version=False)

    assert (pinned / ".python-version").read_text().strip() == "3.13"
    assert ".python-version" not in files(unpinned)


def test_dependabot_holds_back_pyside_majors_for_qt_only(tmp_path):
    qt = generate(tmp_path / "a", project_type="qt_app")
    plain = generate(tmp_path / "b")

    assert "pyside6*" in (qt / ".github/dependabot.yml").read_text()
    assert "pyside6" not in (plain / ".github/dependabot.yml").read_text()


@pytest.mark.parametrize(
    "ide, present", [("nvim", ".nvim.lua"), ("vscode", ".vscode/settings.json")]
)
def test_the_ide_files_follow_the_ide(tmp_path, ide, present):
    project = generate(tmp_path, ide=ide)

    assert present in files(project)
    others = {".nvim.lua", ".vscode/settings.json"} - {present}
    assert not others & files(project)


def test_ide_none_adds_no_editor_files(tmp_path):
    project = generate(tmp_path, ide="none")

    assert not {".nvim.lua", ".vscode/settings.json"} & files(project)


# project-type specific


def test_library_has_no_qt_files(tmp_path):
    project = generate(tmp_path, project_type="library")

    check_well_formed(project)
    assert makefile_modules(project) == ["general/python"]
    assert "BUILD_PREREQS" not in (project / "Makefile").read_text()
    assert "src/demo_pkg/main.py" not in files(project)
    assert not any("resources" in name or "qml" in name for name in files(project))
    assert "pyside6" not in (project / "pyproject.toml").read_text().lower()


def test_qt_app_has_resources_and_a_main(tmp_path):
    project = generate(tmp_path, project_type="qt_app", ide="vscode")

    check_well_formed(project)
    assert {
        "src/demo_pkg/main.py",
        "src/demo_pkg/resources/resources.qrc",
        ".vscode/launch.json",
    } <= files(project)
    assert "pyside6" in (project / "pyproject.toml").read_text().lower()
    assert makefile_modules(project) == ["general/python", "general/qt"]
    assert "BUILD_PREREQS = qrc" in (project / "Makefile").read_text()
    assert "PYTEST_CMD = QT_QPA_PLATFORM=offscreen" in (project / "Makefile").read_text()


def test_qml_app_adds_qml_and_the_qmlls_script(tmp_path):
    project = generate(tmp_path, project_type="qml_app")

    check_well_formed(project)
    assert "src/demo_pkg/qml/qmldir" in files(project)
    assert "generate_qmlls_config.py" in files(project)
    assert makefile_modules(project) == ["general/python", "general/qt", "general/qml"]


def test_bundling_adds_the_spec_and_the_macos_app_targets(tmp_path):
    project = generate(tmp_path, project_type="qt_app", bundle_app=True, macos_app=True)

    check_well_formed(project)
    assert "demo-project.spec" in files(project)
    assert makefile_modules(project) == [
        "general/python",
        "general/qt",
        "general/bundle",
        "general/macos-app",
    ]
    assert "pyinstaller" in (project / "pyproject.toml").read_text()


def test_bundling_is_not_asked_for_a_library(tmp_path):
    project = generate(tmp_path, project_type="library", bundle_app=True)

    assert "demo-project.spec" not in files(project)
    assert "bundle_app" not in answers(project)


def test_pypi_publishing_adds_the_module_name_and_urls(tmp_path):
    project = generate(tmp_path, publish_to_pypi=True, pypi_name="demo-on-pypi")

    check_well_formed(project)
    pyproject = tomllib.loads((project / "pyproject.toml").read_text())
    assert makefile_modules(project) == ["general/python", "general/pypi"]
    assert pyproject["project"]["name"] == "demo-on-pypi"
    assert pyproject["project"]["urls"]["Homepage"].endswith("/sowwic/demo-project")
    assert answers(project)["pypi_name"] == "demo-on-pypi"


def test_pypi_name_defaults_to_the_project_slug(tmp_path):
    project = generate(tmp_path, publish_to_pypi=True)

    pyproject = tomllib.loads((project / "pyproject.toml").read_text())

    assert pyproject["project"]["name"] == "demo-project"


def test_pypi_is_off_by_default(tmp_path):
    project = generate(tmp_path, pypi_name="ignored")

    check_well_formed(project)
    pyproject = tomllib.loads((project / "pyproject.toml").read_text())
    assert makefile_modules(project) == ["general/python"]
    assert "urls" not in pyproject["project"]
    assert pyproject["project"]["name"] == "demo-project"
    assert "pypi_name" not in answers(project)


def test_computed_values_are_not_saved_in_the_answers(tmp_path):
    saved = answers(generate(tmp_path, project_type="qt_app"))

    assert not {"is_qt", "is_qml", "bundle", "macos", "dist_name"} & set(saved)
    assert saved["project_type"] == "qt_app"


def test_zed_config_is_only_for_qt_projects(tmp_path):
    qt = generate(tmp_path / "a", project_type="qt_app", ide="zed")
    lib = generate(tmp_path / "b", project_type="library", ide="zed")

    assert ".zed/debug.json" in files(qt)
    assert not any(name.startswith(".zed") for name in files(lib))


def test_the_makefile_fetches_the_shared_modules(tmp_path):
    makefile = (generate(tmp_path) / "Makefile").read_text()

    assert "MAKEFILES_REF ?= v1" in makefile
    assert (
        "https://raw.githubusercontent.com/sowwic/makefiles/$(MAKEFILES_REF)" in makefile
    )
    assert ".make/%.mk:" in makefile
    assert "include $(MAKEFILES_MODULES:%=.make/%.mk)" in makefile
    assert (
        "APP_NAME = demo-project" in makefile and "PACKAGE_NAME = demo_pkg" in makefile
    )


def test_the_fetched_modules_are_not_git_ignored(tmp_path):
    gitignore = (generate(tmp_path) / ".gitignore").read_text().splitlines()

    assert not {".make", ".make/", ".make/*", "*.mk"} & set(gitignore)
