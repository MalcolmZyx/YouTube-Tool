"""comment label

Labels for the constructive-criticism classifier. The table is not tied to a client, and the downgrade drops only it.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-26 09:12:40.118204

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: str | Sequence[str] | None = '0003'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('comment_label',
    sa.Column('comment_id', sa.Text(), nullable=False),
    sa.Column('status', sa.Text(), nullable=False),
    sa.Column('depth', sa.Text(), nullable=True),
    sa.Column('aspects', postgresql.ARRAY(sa.Text()), server_default='{}', nullable=False),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('video_id', sa.Text(), nullable=True),
    sa.Column('video_title', sa.Text(), nullable=True),
    sa.Column('stratum', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('like_count', sa.Integer(), nullable=True),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('queue_mode', sa.Text(), nullable=False),
    sa.Column('labeled_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('previous', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint("(status IN ('constructive', 'not_constructive')) = (text IS NOT NULL)", name=op.f('ck_comment_label_text_only_when_kept')),
    sa.CheckConstraint("aspects <@ ARRAY['audio', 'video_quality', 'pacing', 'content_accuracy', 'title_thumbnail', 'delivery', 'other']::text[]", name=op.f('ck_comment_label_aspects_known')),
    sa.CheckConstraint("depth IS NULL OR depth IN ('basic', 'specific', 'advanced')", name=op.f('ck_comment_label_depth_known')),
    sa.CheckConstraint("status = 'constructive' OR (depth IS NULL AND aspects = '{}')", name=op.f('ck_comment_label_tags_only_when_constructive')),
    sa.CheckConstraint("status IN ('constructive', 'not_constructive', 'discarded', 'skipped')", name=op.f('ck_comment_label_status_known')),
    sa.PrimaryKeyConstraint('comment_id', name=op.f('pk_comment_label'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('comment_label')
