import pytest
from natilah.ingestion.json_upload import JSONUploadSource
from natilah.ingestion.synthetic import SyntheticDataGenerator
from natilah.models.enums import OpportunityType


def test_synthetic_data_generator():
    generator = SyntheticDataGenerator(
        num_nodes=8,
        gpus_per_node=8,
        num_jobs=30,
        time_window_hours=6,
        seed=123,
    )
    dataset = generator.generate()

    assert len(dataset.nodes) == 8
    assert len(dataset.gpus) == 64
    assert len(dataset.jobs) == 30
    assert len(dataset.allocations) > 0
    assert len(dataset.samples) > 0
    assert len(dataset.decisions) > 0

    # Ensure injected inefficiency decisions exist
    has_over_alloc = any(
        j.constraints.get("injected_pattern") == "over_allocation"
        for j in dataset.jobs
    )
    assert has_over_alloc, "Synthetic dataset should contain injected over-allocation pattern"


@pytest.mark.asyncio
async def test_json_upload_datasource(async_session, synthetic_dataset):
    json_data = synthetic_dataset.model_dump(mode="json")
    uploader = JSONUploadSource(json_data)
    issues = uploader.validate()
    assert len(issues) == 0

    result = await uploader.ingest(async_session)
    assert result.nodes == 16
    assert result.gpus == 128
    assert result.jobs == 50
    assert result.source == "json_upload"
