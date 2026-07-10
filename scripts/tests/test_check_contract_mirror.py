"""The guard: contracts/ must byte-mirror every published apps/*/config/schemas/*.json."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_contract_mirror import expected_mirrors, find_mirror_problems, fix, main


def _repo(tmp_path: Path, apps: dict[str, bytes], contracts: dict[str, bytes] | None = None) -> Path:
    for app, payload in apps.items():
        schemas = tmp_path / "apps" / app / "config" / "schemas"
        schemas.mkdir(parents=True)
        (schemas / f"{app}-schema.json").write_bytes(payload)
    if contracts is not None:
        cdir = tmp_path / "contracts"
        cdir.mkdir()
        for name, payload in contracts.items():
            (cdir / name).write_bytes(payload)
    return tmp_path


def test_faithful_mirror_passes(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"dla": b"{}"}, {"dla-schema.json": b"{}"})
    assert find_mirror_problems(root) == []
    assert main([], root=root) == 0


def test_missing_mirror_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"dla": b"{}"}, {})
    problems = find_mirror_problems(root)
    assert len(problems) == 1
    assert "missing mirror" in problems[0]
    assert main([], root=root) == 1


def test_differing_mirror_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"dla": b"{'a':1}"}, {"dla-schema.json": b"{}"})
    problems = find_mirror_problems(root)
    assert len(problems) == 1
    assert "mirror differs" in problems[0]


def test_stale_mirror_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"dla": b"{}"}, {"dla-schema.json": b"{}", "old.json": b"{}"})
    problems = find_mirror_problems(root)
    assert len(problems) == 1
    assert "stale mirror" in problems[0]


def test_missing_contracts_dir_reports_only_missing(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"dla": b"{}"}, contracts=None)
    problems = find_mirror_problems(root)
    assert problems == [
        "missing mirror: contracts/dla-schema.json (source: apps/dla/config/schemas/dla-schema.json)"
    ]


def test_filename_collision_raises(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"a": b"{}", "b": b"{}"})
    for app in ("a", "b"):
        src = root / "apps" / app / "config" / "schemas" / f"{app}-schema.json"
        src.rename(src.with_name("same-schema.json"))
    with pytest.raises(ValueError, match="collision"):
        expected_mirrors(root)


def test_fix_writes_updates_and_drops_stale(tmp_path: Path) -> None:
    root = _repo(
        tmp_path,
        {"dla": b"{'v':2}"},
        {"dla-schema.json": b"{'v':1}", "old.json": b"{}"},
    )
    assert main(["--fix"], root=root) == 0
    assert (root / "contracts" / "dla-schema.json").read_bytes() == b"{'v':2}"
    assert not (root / "contracts" / "old.json").exists()
    assert find_mirror_problems(root) == []


def test_fix_creates_contracts_dir(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"dla": b"{}"}, contracts=None)
    fix(root)
    assert (root / "contracts" / "dla-schema.json").read_bytes() == b"{}"


def test_real_repo_mirror_is_faithful() -> None:
    """The committed contracts/ must mirror the committed app schemas."""
    root = Path(__file__).resolve().parent.parent.parent
    assert find_mirror_problems(root) == []


def test_main_defaults_to_repo_root() -> None:
    assert main([]) == 0
