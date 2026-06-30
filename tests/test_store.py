import pytest

from app.ingest.store import _validate_rebuild_args


def test_validate_rebuild_args_rejects_full_rebuild_with_refresh_types() -> None:
    with pytest.raises(ValueError, match="cannot be combined"):
        _validate_rebuild_args(full_rebuild=True, refresh_types=("themes",))


def test_validate_rebuild_args_rejects_unknown_refresh_types() -> None:
    with pytest.raises(ValueError, match="Unknown chunk type"):
        _validate_rebuild_args(full_rebuild=False, refresh_types=("unknown",))


def test_validate_rebuild_args_accepts_theme_refresh() -> None:
    _validate_rebuild_args(full_rebuild=False, refresh_types=("themes",))
