import json

import pytest

from local_dev_agent.context import ArtifactReadError, FileSystemToolResultArtifactStore


def _persist(store: FileSystemToolResultArtifactStore):
    return store.persist(
        tool_use_id="toolu-1",
        content={"alpha": "甲乙丙丁", "count": 1},
        is_error=False,
    )


def test_artifact_store_reads_a_verified_content_page_without_exposing_its_root(tmp_path) -> None:
    store = FileSystemToolResultArtifactStore(tmp_path)
    artifact = _persist(store)
    expected_content = json.dumps(
        {"alpha": "甲乙丙丁", "count": 1},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    first_page = store.read_text_page(
        artifact_ref=artifact.relative_path,
        offset=0,
        max_characters=10,
    )
    second_page = store.read_text_page(
        artifact_ref=artifact.relative_path,
        offset=first_page.next_offset or 0,
        max_characters=len(expected_content),
    )

    assert first_page.content == expected_content[:10]
    assert first_page.next_offset == 10
    assert first_page.truncated is True
    assert second_page.content == expected_content[10:]
    assert second_page.next_offset is None
    assert second_page.total_characters == len(expected_content)
    assert str(tmp_path) not in first_page.artifact_ref


@pytest.mark.parametrize(
    "artifact_ref",
    [
        "../tool-results/" + "a" * 64 + ".json",
        "tool-results\\" + "a" * 64 + ".json",
        "C:/tool-results/" + "a" * 64 + ".json",
        "tool-results/not-a-digest.json",
        "tool-results/" + "0" * 64 + ".json",
    ],
)
def test_artifact_store_rejects_uncontrolled_or_unknown_references(tmp_path, artifact_ref) -> None:
    store = FileSystemToolResultArtifactStore(tmp_path)
    (tmp_path / "secret.txt").write_text("不能读取", encoding="utf-8")

    with pytest.raises(ArtifactReadError):
        store.read_text_page(artifact_ref=artifact_ref, offset=0, max_characters=10)


def test_artifact_store_rejects_a_tampered_payload_before_returning_content(tmp_path) -> None:
    store = FileSystemToolResultArtifactStore(tmp_path)
    artifact = _persist(store)
    target = tmp_path / artifact.relative_path
    target.write_bytes(target.read_bytes() + b" ")

    with pytest.raises(ArtifactReadError, match="摘要校验失败"):
        store.read_text_page(artifact_ref=artifact.relative_path, offset=0, max_characters=10)


@pytest.mark.parametrize(
    ("offset", "max_characters"), [(-1, 1), (0, 0), (True, 1), (0, True)])
def test_artifact_store_validates_pagination_bounds(tmp_path, offset, max_characters) -> None:
    store = FileSystemToolResultArtifactStore(tmp_path)
    artifact = _persist(store)

    with pytest.raises(ArtifactReadError):
        store.read_text_page(
            artifact_ref=artifact.relative_path,
            offset=offset,
            max_characters=max_characters,
        )
