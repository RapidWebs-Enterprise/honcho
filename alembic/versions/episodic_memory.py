"""Migration for episodic memory tables."""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    """Add episodes, summaries, and insights tables."""
    # Episodes table
    op.create_table(
        'episodes',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('session_id', sa.String(), nullable=False, index=True),
        sa.Column('workspace_name', sa.String(), nullable=False, index=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('message_count', sa.Integer(), nullable=False, default=0),
        sa.Column('status', sa.String(), nullable=False, default='raw'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['workspace_name'],
            ['workspaces.name'],
        ),
    )

    # Summaries table
    op.create_table(
        'summaries',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('episode_id', sa.String(), nullable=False, index=True),
        sa.Column('key_points', sa.JSON(), nullable=False, default=list),
        sa.Column('decisions', sa.JSON(), nullable=False, default=list),
        sa.Column('open_questions', sa.JSON(), nullable=False, default=list),
        sa.Column('summary_text', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['episode_id'],
            ['episodes.id'],
            ondelete='CASCADE',
        ),
    )

    # Insights table
    op.create_table(
        'insights',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('workspace_name', sa.String(), nullable=False, index=True),
        sa.Column('topic', sa.String(), nullable=False, index=True),
        sa.Column('pattern', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False, default=0.5),
        sa.Column('supporting_summary_ids', sa.JSON(), nullable=False, default=list),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
    )


def downgrade() -> None:
    """Remove episodic memory tables."""
    op.drop_table('insights')
    op.drop_table('summaries')
    op.drop_table('episodes')
