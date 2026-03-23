"""vector_1024_to_768

Revision ID: ccb8392f3316
Revises: 35dce51cf74b
Create Date: 2026-03-23 09:48:11.882676

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'ccb8392f3316'
down_revision: Union[str, Sequence[str], None] = '35dce51cf74b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Switch embedding columns from 1024 to 768 dims (all-mpnet-base-v2)."""
    # Drop existing data (all zeros from failed gte-large CUDA anyway)
    for table in ("articles", "entities", "facts", "reports"):
        op.execute(f"UPDATE {table} SET embedding = NULL WHERE embedding IS NOT NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector(768)")


def downgrade() -> None:
    """Revert to 1024 dims."""
    for table in ("articles", "entities", "facts", "reports"):
        op.execute(f"UPDATE {table} SET embedding = NULL WHERE embedding IS NOT NULL")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN embedding TYPE vector(1024)")
