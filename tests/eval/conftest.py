import importlib.util

import pytest


@pytest.fixture
def api():
    if not importlib.util.find_spec("eval.models"):
        return None
    from eval import models

    return models
