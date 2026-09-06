import os
import tempfile

# Use an isolated temporary database for tests (must be set before app import).
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmp, 'test.db')}"
os.environ["AUTO_SEED"] = "1"
os.environ["JWT_SECRET"] = "test-secret-key-that-is-long-enough-32-bytes"
