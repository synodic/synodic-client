"""Tests for PackageStateStore."""

from __future__ import annotations

from synodic_client.application.package_state import PackageStateStore


class TestRecordUpdatesCompleted:
    """Tests for PackageStateStore.record_updates_completed()."""

    @staticmethod
    def test_clears_has_update_flag() -> None:
        """Completing an update clears the has_update flag."""
        store = PackageStateStore()
        store.set_check_results({'pip': {'requests': '2.32.0'}})

        state = store.get('pip', 'requests')
        assert state is not None
        assert state.has_update is True

        store.record_updates_completed('pip', {'requests': ('2.31.0', '2.32.0')})

        state = store.get('pip', 'requests')
        assert state is not None
        assert state.has_update is False
        assert state.installed_version == '2.32.0'

    @staticmethod
    def test_ignores_unknown_packages() -> None:
        """Packages not in the store are silently ignored."""
        store = PackageStateStore()
        store.set_check_results({'pip': {'requests': '2.32.0'}})

        store.record_updates_completed('pip', {'unknown-pkg': ('1.0', '2.0')})

        # Original entry unchanged
        state = store.get('pip', 'requests')
        assert state is not None
        assert state.has_update is True

    @staticmethod
    def test_emits_state_changed() -> None:
        """Signal fires when at least one package state is updated."""
        store = PackageStateStore()
        store.set_check_results({'pip': {'requests': '2.32.0'}})

        calls: list[bool] = []
        store.state_changed.connect(lambda: calls.append(True))

        store.record_updates_completed('pip', {'requests': ('2.31.0', '2.32.0')})
        assert len(calls) == 1

    @staticmethod
    def test_no_signal_when_nothing_changed() -> None:
        """No signal when version_map has no matching entries."""
        store = PackageStateStore()
        store.set_check_results({'pip': {'requests': '2.32.0'}})

        calls: list[bool] = []
        store.state_changed.connect(lambda: calls.append(True))

        store.record_updates_completed('pip', {'no-match': ('1.0', '2.0')})
        assert len(calls) == 0
