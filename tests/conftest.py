import os
import tempfile

# Every test run gets a throwaway database. Semantic memory starts off so the
# core tests are fast; test_memory.py switches the real model on.
os.environ["AIOS_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["AIOS_EMBEDDINGS"] = "off"
