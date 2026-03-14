"""Tests for ReportStore versioned report storage.

Validates version auto-incrementing, content deduplication via SHA256
hashing, version retrieval, change detection, and investigation listing.
"""

from __future__ import annotations

import pytest

from osint_system.reporting.report_store import ReportRecord, ReportStore


@pytest.fixture
def store() -> ReportStore:
    """ReportStore with no persistence (in-memory only)."""
    return ReportStore(output_dir="test-reports/")


@pytest.fixture
def markdown_v1() -> str:
    """First version of a Markdown report."""
    return (
        "# Intelligence Report: inv-test-001\n\n"
        "## Executive Summary\n\n"
        "We assess with moderate confidence that military buildup is occurring.\n\n"
        "## Key Findings\n\n"
        "### Finding 1: Troop movements detected\n\n"
        "**Confidence:** High (88%)\n"
    )


@pytest.fixture
def markdown_v2() -> str:
    """Second version with updated findings."""
    return (
        "# Intelligence Report: inv-test-001\n\n"
        "## Executive Summary\n\n"
        "We assess with HIGH confidence that military buildup is occurring.\n\n"
        "## Key Findings\n\n"
        "### Finding 1: Troop movements confirmed\n\n"
        "**Confidence:** High (92%)\n\n"
        "### Finding 2: Additional vehicle staging observed\n\n"
        "**Confidence:** Moderate (71%)\n"
    )


class TestSaveReport:
    """Tests for save_report method."""

    @pytest.mark.asyncio
    async def test_save_report_creates_record(
        self, store: ReportStore, markdown_v1: str
    ) -> None:
        """save_report returns ReportRecord with version=1."""
        record = await store.save_report("inv-001", markdown_v1)

        assert isinstance(record, ReportRecord)
        assert record.investigation_id == "inv-001"
        assert record.version == 1
        assert record.markdown_content == markdown_v1
        assert len(record.content_hash) == 64  # SHA256 hex digest

    @pytest.mark.asyncio
    async def test_save_report_increments_version(
        self, store: ReportStore, markdown_v1: str, markdown_v2: str
    ) -> None:
        """Saving different content increments version number."""
        r1 = await store.save_report("inv-001", markdown_v1)
        r2 = await store.save_report("inv-001", markdown_v2)

        assert r1.version == 1
        assert r2.version == 2
        assert r1.content_hash != r2.content_hash

    @pytest.mark.asyncio
    async def test_save_report_skips_unchanged(
        self, store: ReportStore, markdown_v1: str
    ) -> None:
        """Saving same content twice returns existing record without new version."""
        r1 = await store.save_report("inv-001", markdown_v1)
        r2 = await store.save_report("inv-001", markdown_v1)

        assert r1.version == 1
        assert r2.version == 1
        assert r1.content_hash == r2.content_hash

        # Should only have 1 version stored
        versions = await store.list_versions("inv-001")
        assert len(versions) == 1


class TestGetLatest:
    """Tests for get_latest method."""

    @pytest.mark.asyncio
    async def test_get_latest(
        self, store: ReportStore, markdown_v1: str, markdown_v2: str
    ) -> None:
        """get_latest returns the most recent version."""
        await store.save_report("inv-001", markdown_v1)
        await store.save_report("inv-001", markdown_v2)

        latest = await store.get_latest("inv-001")
        assert latest is not None
        assert latest.version == 2
        assert latest.markdown_content == markdown_v2

    @pytest.mark.asyncio
    async def test_get_latest_nonexistent(self, store: ReportStore) -> None:
        """get_latest returns None for unknown investigation."""
        result = await store.get_latest("inv-nonexistent")
        assert result is None


class TestGetVersion:
    """Tests for get_version method."""

    @pytest.mark.asyncio
    async def test_get_version(
        self, store: ReportStore, markdown_v1: str, markdown_v2: str
    ) -> None:
        """get_version returns specific version by number."""
        await store.save_report("inv-001", markdown_v1)
        await store.save_report("inv-001", markdown_v2)

        v1 = await store.get_version("inv-001", 1)
        v2 = await store.get_version("inv-001", 2)

        assert v1 is not None
        assert v1.version == 1
        assert v1.markdown_content == markdown_v1

        assert v2 is not None
        assert v2.version == 2
        assert v2.markdown_content == markdown_v2

    @pytest.mark.asyncio
    async def test_get_version_nonexistent(
        self, store: ReportStore, markdown_v1: str
    ) -> None:
        """get_version returns None for unknown version number."""
        await store.save_report("inv-001", markdown_v1)
        result = await store.get_version("inv-001", 99)
        assert result is None


class TestListVersions:
    """Tests for list_versions method."""

    @pytest.mark.asyncio
    async def test_list_versions(
        self, store: ReportStore, markdown_v1: str, markdown_v2: str
    ) -> None:
        """list_versions returns all versions in order."""
        await store.save_report("inv-001", markdown_v1)
        await store.save_report("inv-001", markdown_v2)

        versions = await store.list_versions("inv-001")
        assert len(versions) == 2
        assert versions[0].version == 1
        assert versions[1].version == 2

    @pytest.mark.asyncio
    async def test_list_versions_empty(self, store: ReportStore) -> None:
        """list_versions returns empty list for unknown investigation."""
        versions = await store.list_versions("inv-nonexistent")
        assert versions == []


class TestHasChanged:
    """Tests for has_changed method."""

    @pytest.mark.asyncio
    async def test_has_changed_new_investigation(
        self, store: ReportStore, markdown_v1: str
    ) -> None:
        """has_changed returns True for new investigation (no prior version)."""
        result = await store.has_changed("inv-new", markdown_v1)
        assert result is True

    @pytest.mark.asyncio
    async def test_has_changed_same_content(
        self, store: ReportStore, markdown_v1: str
    ) -> None:
        """has_changed returns False when content matches latest."""
        await store.save_report("inv-001", markdown_v1)
        result = await store.has_changed("inv-001", markdown_v1)
        assert result is False

    @pytest.mark.asyncio
    async def test_has_changed_different_content(
        self, store: ReportStore, markdown_v1: str, markdown_v2: str
    ) -> None:
        """has_changed returns True when content differs from latest."""
        await store.save_report("inv-001", markdown_v1)
        result = await store.has_changed("inv-001", markdown_v2)
        assert result is True


class TestListInvestigations:
    """Tests for list_investigations method."""

    @pytest.mark.asyncio
    async def test_list_investigations(
        self, store: ReportStore, markdown_v1: str, markdown_v2: str
    ) -> None:
        """list_investigations returns summary with report count."""
        await store.save_report("inv-001", markdown_v1)
        await store.save_report("inv-001", markdown_v2)
        await store.save_report("inv-002", markdown_v1)

        investigations = await store.list_investigations()
        assert len(investigations) == 2

        inv_001 = next(
            i for i in investigations if i["investigation_id"] == "inv-001"
        )
        inv_002 = next(
            i for i in investigations if i["investigation_id"] == "inv-002"
        )

        assert inv_001["report_count"] == 2
        assert inv_001["latest_version"] == 2

        assert inv_002["report_count"] == 1
        assert inv_002["latest_version"] == 1


class TestContentHash:
    """Tests for content hashing behavior."""

    @pytest.mark.asyncio
    async def test_content_hash_deterministic(
        self, store: ReportStore
    ) -> None:
        """Same content always produces the same hash."""
        content = "Identical content for hashing test"
        hash_1 = store._compute_hash(content)
        hash_2 = store._compute_hash(content)
        assert hash_1 == hash_2
        assert len(hash_1) == 64  # SHA256 hex digest

    @pytest.mark.asyncio
    async def test_content_hash_differs_for_different_content(
        self, store: ReportStore
    ) -> None:
        """Different content produces different hashes."""
        hash_1 = store._compute_hash("Content A")
        hash_2 = store._compute_hash("Content B")
        assert hash_1 != hash_2


class TestPersistence:
    """Tests for optional JSON persistence."""

    @pytest.mark.asyncio
    async def test_persistence_writes_file(
        self, tmp_path: pytest.TempPathFactory, markdown_v1: str
    ) -> None:
        """When persistence_path is set, metadata is written to JSON."""
        persist_path = str(tmp_path / "report_meta.json")
        store = ReportStore(
            output_dir="test-reports/",
            persistence_path=persist_path,
        )

        await store.save_report("inv-001", markdown_v1)

        import json
        from pathlib import Path

        data = json.loads(Path(persist_path).read_text(encoding="utf-8"))
        assert "inv-001" in data
        assert len(data["inv-001"]) == 1
        assert data["inv-001"][0]["version"] == 1
        # markdown_content should be excluded from persistence
        assert "markdown_content" not in data["inv-001"][0]
