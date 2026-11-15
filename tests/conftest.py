import pytest

from src.catalog import load_catalog
from src.config import Config
from src.logging_setup import close_loggers
from src.retriever import KnowledgeBase


@pytest.fixture(scope="session")
def songs():
    return load_catalog("data/songs.csv")


@pytest.fixture(scope="session")
def kb(songs):
    k = KnowledgeBase.load("knowledge")
    k.index_catalog(songs)
    return k


@pytest.fixture()
def cfg(tmp_path):
    """Config whose logs go to a temp dir so tests never write into logs/."""
    c = Config(log_dir=str(tmp_path / "logs"))
    yield c
    close_loggers()
