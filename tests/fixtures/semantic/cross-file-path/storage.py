from pathlib import Path


def read_document(name):
    return (Path("documents") / name).read_text()
