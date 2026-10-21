from countersign.aws import make_client


def _isolate(monkeypatch, tmp_path):
    for k in ("AWS_REGION", "AWS_DEFAULT_REGION", "AWS_PROFILE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "none"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "none"))


def test_falls_back_to_us_east_1_when_no_region_configured(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    assert make_client("bedrock-runtime").meta.region_name == "us-east-1"


def test_configured_region_wins(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
    assert make_client("s3").meta.region_name == "eu-west-1"
