import hashlib

from server.cosyvoice_prepare import verify, FILES, V3_FILES, V3_SMALL_FILES, V3_REVISION


def test_weight_verification_checks_size_and_sha256(tmp_path):
    path = tmp_path / "weight"
    path.write_bytes(b"model")
    assert verify(path, 5, hashlib.sha256(b"model").hexdigest())
    assert not verify(path, 4, hashlib.sha256(b"model").hexdigest())
    assert not verify(path, 5, "0" * 64)


def test_small_file_verification_uses_git_blob_hash(tmp_path):
    path = tmp_path / "config"
    path.write_bytes(b"config")
    assert verify(path, 6, hashlib.sha1(b"blob 6\0config").hexdigest(), git_blob=True)
    assert not verify(path, 6, hashlib.sha1(b"config").hexdigest(), git_blob=True)


def test_third_generation_manifest_is_pinned_and_distinct():
    assert V3_REVISION == "29e01c4e8d000f4bcd70751be16fa94bf3d85a18"
    assert V3_FILES["llm.pt"] != FILES["llm.pt"]
    assert "speech_tokenizer_v3.onnx" in V3_FILES
    assert "cosyvoice3.yaml" in V3_SMALL_FILES
