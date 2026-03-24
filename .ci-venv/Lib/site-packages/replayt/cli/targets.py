"""Resolve MODULE:VAR, .py, and .yaml workflow targets."""

from __future__ import annotations

import importlib
import importlib.util
import re
from pathlib import Path
from typing import Any

import typer

from replayt.workflow import Workflow
from replayt.yaml_workflow import load_workflow_yaml, workflow_from_spec


def _workflow_objects(obj: Any) -> list[tuple[str, Workflow]]:
    return [(name, value) for name, value in vars(obj).items() if isinstance(value, Workflow)]


def _suggest_workflow_attr_name(workflows: list[tuple[str, Workflow]]) -> str:
    """Pick a conventional export name for copy-paste hints (prefer ``wf``, then ``workflow``)."""

    names = [name for name, _ in workflows]
    if "wf" in names:
        return "wf"
    if "workflow" in names:
        return "workflow"
    return min(names)


# Dotted Python module path without ":" — common first-hour mistake (MODULE:VAR).
_DOTTED_MODULEISH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")


def _looks_like_dotted_module_target(target: str) -> bool:
    if not target or "/" in target or "\\" in target:
        return False
    return _DOTTED_MODULEISH.fullmatch(target) is not None


def _is_windows_drive_path_target(target: str) -> bool:
    """True for ``C:\\...`` / ``C:/...`` so the drive letter colon is not treated as MODULE:VAR."""

    if len(target) < 3:
        return False
    return target[0].isalpha() and target[1] == ":" and target[2] in "/\\"


def _wrong_workflow_type_message(target: str, obj: Any) -> str:
    """Explain MODULE:VAR / file targets that resolve to a non-Workflow object."""

    t = type(obj)
    mod = getattr(t, "__module__", "") or ""
    name = getattr(t, "__qualname__", t.__name__)
    if mod in ("", "builtins"):
        type_label = name
    else:
        type_label = f"{mod}.{name}"
    return (
        f"Target {target!r} resolved to {type_label}, not replayt.workflow.Workflow. "
        "Pass the name of the variable that holds your built Workflow instance (often `wf` or `workflow`), "
        "not a class, plain dict, or factory function. "
        f"After fixing the export, `replayt doctor --skip-connectivity --target {target}` "
        "checks the graph without executing."
    )


def _unsupported_existing_workflow_file_message(target: str, path: Path) -> str:
    """*path* exists and is a file, but is not an executable ``.py`` / YAML workflow entry."""

    display = str(path)
    base = (
        f"Target {display!r} exists on disk but is not a `.py` or `.yaml` / `.yml` workflow file. "
        "`replayt run` needs the workflow entrypoint; inputs are passed separately."
    )
    suf = path.suffix.lower()
    name = path.name
    if suf == ".json":
        return (
            f"{base} For JSON payloads use `--inputs-file {name}` with a workflow target "
            f"(for example `replayt run workflow.py --inputs-file {name}`) or set `inputs_file` under "
            "`.replaytrc.toml` / `[tool.replayt]`."
        )
    if suf in {".toml", ".ini", ".cfg"}:
        return (
            f"{base} Config files are not executed. Pass `MODULE:VAR`, a `.py` / `.yaml` workflow path, "
            "or rely on project defaults from `pyproject.toml` / `.replaytrc.toml` "
            "(`replayt config --format json` shows the resolved default target)."
        )
    if suf in {".md", ".rst", ".txt"}:
        return (
            f"{base} Documentation files are not workflows; open `docs/QUICKSTART.md` or run "
            "`replayt init --list` / `replayt try --list` for a copy-paste starting target."
        )
    return (
        f"{base} If this file holds inputs, add `--inputs-file` and pass the workflow as `TARGET` "
        "(see `Default inputs file` in `src/replayt_examples/README.md`)."
    )


def _target_path_not_found_message(target: str, path: Path) -> str:
    """Explain missing targets with copy-paste fixes (junior onboarding)."""

    base = (
        f"Expected a MODULE:VAR target, a `.py` / `.yaml` workflow path, or `replayt try` to copy an example; "
        f"nothing exists at {path!r}."
    )
    if _looks_like_dotted_module_target(target):
        return (
            f"{base} If you meant a Python module, put a colon before the workflow variable "
            f"(for example: `replayt run {target}:wf`). "
            f"Run `replayt doctor --skip-connectivity --target {target}:wf` after imports work."
        )
    # Only append extensions when *target* has no pathlib-style suffix, otherwise
    # `replayt_examples.e01_hello_world` would wrongly become `replayt_examples.py`.
    if not path.suffix:
        py_sibling = path.parent / f"{path.name}.py"
        yml_sibling = path.parent / f"{path.name}.yml"
        yaml_sibling = path.parent / f"{path.name}.yaml"
        if py_sibling.is_file():
            return (
                f"{base} `{py_sibling.name}` exists here — pass that path "
                f"(for example: `replayt run {py_sibling}`) or set `target` in `.replaytrc.toml`."
            )
        if yml_sibling.is_file():
            return (
                f"{base} `{yml_sibling.name}` exists here — pass that path "
                f"(for example: `replayt run {yml_sibling}`) or set `target` in `.replaytrc.toml`."
            )
        if yaml_sibling.is_file():
            return (
                f"{base} `{yaml_sibling.name}` exists here — pass that path "
                f"(for example: `replayt run {yaml_sibling}`) or set `target` in `.replaytrc.toml`."
            )
    return base


def _python_file_import_bad_parameter(path: Path, exc: ModuleNotFoundError) -> typer.BadParameter:
    missing = getattr(exc, "name", None)
    inner = repr(missing) if missing else "a dependency"
    return typer.BadParameter(
        f"Importing Python workflow file {path} failed: {inner} is missing "
        "(not installed or not on PYTHONPATH). "
        "Activate the right virtual environment, install your project editable (`pip install -e .`) "
        "if this file imports local packages, or switch to a `MODULE:VAR` target once imports work. "
        f"After it imports, `replayt doctor --skip-connectivity --target {path}` checks the graph without executing."
    )


def _python_file_syntax_bad_parameter(path: Path, exc: SyntaxError) -> typer.BadParameter:
    detail = exc.msg or "invalid syntax"
    location = f"line {exc.lineno}"
    if exc.offset is not None:
        location += f", column {exc.offset}"
    return typer.BadParameter(
        f"Python workflow file {path} has a syntax error at {location}: {detail}. "
        f"Fix the file, then retry. Tip: `python -m py_compile {path}` shows the same parser error directly."
    )


def _python_file_runtime_bad_parameter(path: Path, exc: ImportError) -> typer.BadParameter:
    detail = str(exc).strip() or exc.__class__.__name__
    return typer.BadParameter(
        f"Importing Python workflow file {path} failed with {exc.__class__.__name__}: {detail}. "
        "If this file uses package-relative imports, install your project editable (`pip install -e .`) "
        "and prefer a `MODULE:VAR` target once imports work. "
        f"After that, `replayt doctor --skip-connectivity --target {path}` checks the graph without executing."
    )


def load_python_file(path: Path) -> Any:
    module_name = f"replayt_user_{path.stem}_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise typer.BadParameter(f"Could not import Python workflow file: {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except ModuleNotFoundError as exc:
        raise _python_file_import_bad_parameter(path, exc) from exc
    except SyntaxError as exc:
        raise _python_file_syntax_bad_parameter(path, exc) from exc
    except ImportError as exc:
        raise _python_file_runtime_bad_parameter(path, exc) from exc
    for attr in ("wf", "workflow"):
        if hasattr(module, attr):
            return getattr(module, attr)
    workflows = _workflow_objects(module)
    if len(workflows) == 1:
        return workflows[0][1]
    if workflows:
        names = ", ".join(name for name, _ in workflows)
        raise typer.BadParameter(
            f"Python workflow file {path} defines multiple Workflow objects ({names}); "
            "rename the one you want to `wf` or `workflow`."
        )
    raise typer.BadParameter(
        f"Python workflow file {path} must define `wf` or `workflow`, "
        "or exactly one top-level Workflow object."
    )


def _module_syntax_bad_parameter(target: str, mod_name: str, exc: SyntaxError) -> typer.BadParameter:
    """Syntax errors while loading *mod_name* (import hits a broken ``.py`` file)."""

    detail = exc.msg or "invalid syntax"
    location = f"line {exc.lineno}"
    if exc.offset is not None:
        location += f", column {exc.offset}"
    path_hint = exc.filename or mod_name
    compile_tip = (
        f"Tip: `python -m py_compile {path_hint}` shows the same parser error outside replayt."
        if exc.filename
        else "Fix the syntax error in that module on disk, then retry."
    )
    head = (
        f"Could not import module {mod_name!r} for target {target!r}: syntax error at {location} "
        f"in {path_hint!r}: {detail}. "
    )
    return typer.BadParameter(
        head + f"{compile_tip} "
        f"After the file parses, `replayt doctor --skip-connectivity --target {target}` checks the workflow graph."
    )


def _module_other_import_bad_parameter(target: str, mod_name: str, exc: ImportError) -> typer.BadParameter:
    """ImportError while loading *mod_name* when the module is not simply missing (circular import, etc.)."""

    detail = str(exc).strip() or exc.__class__.__name__
    py_cmd = f'python -c "import {mod_name}"'
    return typer.BadParameter(
        f"Importing module {mod_name!r} for target {target!r} failed with {exc.__class__.__name__}: {detail}. "
        "Python started loading the package but did not finish (often a circular import, import-time side effects, "
        "or a dependency that only fails once the parent package is loading). "
        f"Run {py_cmd} from the same working directory and virtual environment to see the full traceback. "
        f"After imports succeed, `replayt doctor --skip-connectivity --target {target}` checks the workflow graph."
    )


def _module_import_bad_parameter(target: str, mod_name: str, exc: ModuleNotFoundError) -> typer.BadParameter:
    """Turn import failures into onboarding-friendly CLI errors (common footguns)."""

    missing = getattr(exc, "name", None)
    if missing == mod_name:
        msg = (
            f"Could not import module {mod_name!r} from target {target!r}. "
            "Check spelling and your current working directory. "
            "If this is your own code, install it editable from the project root (`pip install -e .`) "
            "or put your package or `src/` tree on `PYTHONPATH` before running replayt. "
            "You can also pass a trusted `workflow.py` or `.yaml` path instead of MODULE:VAR. "
            "After the import works, `replayt doctor --target TARGET` checks the graph without executing."
        )
    else:
        inner = repr(missing) if missing else "a dependency"
        msg = (
            f"Importing {mod_name!r} for target {target!r} failed: {inner} is missing "
            "(not installed or not on PYTHONPATH). "
            "Install that dependency or fix imports inside your package, then retry."
        )
    return typer.BadParameter(msg)


def load_target(target: str) -> Workflow:
    """Resolve *target* to a :class:`~replayt.workflow.Workflow`.

    ``*.py`` paths are loaded with :func:`importlib.util.spec_from_file_location` and
    :meth:`importlib.abc.Loader.exec_module` (same trust model as ``python path/to/file.py``).
    Use only trusted files; prefer ``MODULE:VAR`` from installed
    packages or YAML workflows when inputs are less trusted.
    """
    path = Path(target)
    looks_like_file = path.suffix in {".py", ".yaml", ".yml"} and path.is_file()
    if looks_like_file:
        if path.suffix == ".py":
            obj = load_python_file(path)
        else:
            try:
                obj = workflow_from_spec(load_workflow_yaml(path))
            except RuntimeError as exc:
                msg = str(exc).strip()
                low = msg.lower()
                if "yaml" in low and ("extra" in low or "pip install" in low):
                    raise typer.BadParameter(
                        f"{msg} Then retry `replayt run {path}` "
                        f"(or the same path with `replayt doctor --skip-connectivity --target {path}`)."
                    ) from exc
                raise
    elif ":" in target and not _is_windows_drive_path_target(target):
        mod_name, attr = target.split(":", 1)
        mod_name = mod_name.strip()
        attr = attr.strip()
        if not mod_name or not attr:
            raise typer.BadParameter(
                f"Target {target!r} is not a valid MODULE:VAR reference: "
                "both the import path and the variable name must be non-empty "
                "(for example `replayt_examples.e01_hello_world:wf`). "
                "On Windows, absolute paths like `C:\\path\\to\\workflow.py` are files, not MODULE:VAR."
            )
        if ":" in attr:
            raise typer.BadParameter(
                f"Target {target!r} has more than one ':' in the MODULE:VAR form. "
                "Use exactly one colon between the import path and the Workflow variable "
                f"(for example `{mod_name}:wf`). "
                "On Windows, `C:\\...` paths are filesystem targets, not MODULE:VAR."
            )
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError as exc:
            raise _module_import_bad_parameter(target, mod_name, exc) from exc
        except SyntaxError as exc:
            raise _module_syntax_bad_parameter(target, mod_name, exc) from exc
        except ImportError as exc:
            raise _module_other_import_bad_parameter(target, mod_name, exc) from exc
        if not hasattr(mod, attr):
            workflows = _workflow_objects(mod)
            if workflows:
                names = ", ".join(name for name, _ in workflows)
                pick = _suggest_workflow_attr_name(workflows)
                suggest = f"{mod_name}:{pick}"
                raise typer.BadParameter(
                    f"Module {mod_name!r} has no attribute {attr!r}. "
                    f"It exports Workflow objects named: {names}. "
                    f"Try `replayt run {suggest}` (use the name your module actually defines). "
                    f"Graph preflight without LLM calls: `replayt doctor --skip-connectivity --target {suggest}`."
                )
            raise typer.BadParameter(
                f"Module {mod_name!r} has no attribute {attr!r} and exports no top-level Workflow objects. "
                "Define a `Workflow` at module scope (see `docs/QUICKSTART.md`) and pass `module:variable` "
                f"where `variable` matches that name. Tip: `python -c \"import {mod_name}\"` should succeed first."
            )
        obj = getattr(mod, attr)
    else:
        if not path.exists():
            raise typer.BadParameter(_target_path_not_found_message(target, path))
        if path.is_dir():
            raise typer.BadParameter(
                f"Target {path!r} is a directory. Pass a `.py` or `.yaml` workflow file, "
                "or a MODULE:VAR target such as `my_pkg.workflow:wf`."
            )
        if path.is_file():
            raise typer.BadParameter(_unsupported_existing_workflow_file_message(target, path))
        raise typer.BadParameter(
            f"Target {path!r} is not a supported workflow file. "
            "Use a `.py` or `.yaml` / `.yml` path, or MODULE:VAR (for example `replayt_examples.e01_hello_world:wf`)."
        )
    if not isinstance(obj, Workflow):
        raise typer.BadParameter(_wrong_workflow_type_message(target, obj))
    return obj


def workflow_trust_audit_paths(target: str) -> list[Path]:
    """Resolve filesystem paths to audit for POSIX permission bits (no workflow execution).

    Used by ``replayt doctor`` / ``replayt config`` trust reports: ``replayt run`` executes code from
    the workflow entry file (Python path or the module's ``__file__``). Returns at most one path.
    """

    raw = str(target).strip()
    if not raw:
        return []
    path = Path(raw)
    looks_like_file = path.suffix in {".py", ".yaml", ".yml"} and path.is_file()
    if looks_like_file:
        try:
            return [path.resolve()]
        except OSError:
            return []
    if ":" in raw and not _is_windows_drive_path_target(raw):
        mod_name, _attr = raw.split(":", 1)
        mod_name = mod_name.strip()
        if not mod_name:
            return []
        try:
            mod = importlib.import_module(mod_name)
        except ModuleNotFoundError:
            return []
        fn = getattr(mod, "__file__", None)
        if not fn:
            return []
        p = Path(fn)
        if not p.is_file() or p.suffix != ".py":
            return []
        try:
            return [p.resolve()]
        except OSError:
            return []
    return []
