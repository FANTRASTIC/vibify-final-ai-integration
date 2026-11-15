import json

from src.config import Config
from src.logging_setup import close_loggers, log_request, text_fingerprint


def test_fingerprint_hides_raw_text():
    fp = text_fingerprint("secret listening habits")
    assert "text_raw" not in fp and fp["text_len"] == 23 and len(fp["text_hash"]) == 8
    assert "text_raw" in text_fingerprint("x", log_raw=True)


def test_log_request_writes_json_line(tmp_path):
    cfg = Config(log_dir=str(tmp_path))
    log_request(cfg, {"request_id": "abc", "flags": ["X"]})
    close_loggers()
    line = (tmp_path / "vibify.log").read_text(encoding="utf-8").strip()
    assert json.loads(line) == {"request_id": "abc", "flags": ["X"]}


def test_config_defaults():
    cfg = Config()
    assert sum(cfg.weights_v2.values()) == 10.0
    assert cfg.LOG_RAW_TEXT is False
