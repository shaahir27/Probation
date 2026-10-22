"""Local CLI path validation; no I/O occurs until the requested target is checked."""

from pathlib import Path

import typer


def import_source(path: str | None, source: str | None) -> str:
    """Resolve the contracted --source option or the legacy positional alias."""
    if bool(path) == bool(source):
        raise typer.BadParameter("Provide exactly one --source PATH or positional PATH.")
    return source or path or ""


def synthesis_target(
    *, persona_id: int, size: str, out: str, overwrite: bool, regenerate_fixture: bool
) -> Path:
    """Reject implicit overwrites, fixture writes and escaping output links."""
    if size not in {"tiny", "full"}:
        raise typer.BadParameter("--size must be tiny or full.")
    if not 0 <= persona_id < 20:
        raise typer.BadParameter("--persona-id must be between 0 and 19.")
    target = Path(out) if out else Path("data/synth") / str(persona_id)
    lexical_parts = tuple(part.casefold() for part in target.absolute().parts)
    resolved_parts = tuple(part.casefold() for part in target.resolve().parts)
    fixture_root = ("backend", "tests", "fixtures")
    is_fixture = any(
        parts[i : i + 3] == fixture_root
        for parts in (lexical_parts, resolved_parts)
        for i in range(len(parts) - 2)
    )
    if is_fixture and not regenerate_fixture:
        raise typer.BadParameter("Fixture writes require explicit --regenerate-fixture review.")
    if regenerate_fixture and (not is_fixture or target.name != "tiny_synth"):
        raise typer.BadParameter(
            "--regenerate-fixture requires an explicit tiny_synth fixture path."
        )
    if target.is_symlink() or target.resolve() != target.absolute():
        # Normalize ordinary '..' separately; symlink/junction aliases are never output targets.
        import os

        if target.is_symlink() or target.resolve() != Path(os.path.abspath(target)):
            raise typer.BadParameter("Output target must not traverse a symlink or junction.")
    if target.exists():
        if not target.is_dir():
            raise typer.BadParameter("Output target must be a directory.")
        if any(target.iterdir()) and not overwrite:
            raise typer.BadParameter("Output directory is not empty; review and pass --overwrite.")
        resolved = target.resolve()
        for child in target.rglob("*"):
            if child.is_symlink() or not child.resolve().is_relative_to(resolved):
                raise typer.BadParameter(
                    "Output directory contains a symlink or escaping junction."
                )
    return target
