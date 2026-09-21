"""Migrations for causal relationship tables."""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    """Add kg_causal_relationships table."""
    op.create_table(
        'kg_causal_relationships',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('workspace_name', sa.String(), nullable=False),
        sa.Column('source_entity_id', sa.String(), nullable=False),
        sa.Column('target_entity_id', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False, default=0.5),
        sa.Column('evidence_text', sa.String(), nullable=True),
        sa.Column('inferred', sa.Boolean(), nullable=False, default=True),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ['workspace_name'],
            ['workspaces.name'],
        ),
        sa.ForeignKeyConstraint(
            ['source_entity_id'],
            ['kg_entities.id'],
        ),
        sa.ForeignKeyConstraint(
            ['target_entity_id'],
            ['kg_entities.id'],
        ),
    )

    # Create indexes
    op.create_index(
        'idx_causal_workspace_source',
        'kg_causal_relationships',
        ['workspace_name', 'source_entity_id']
    )
    op.create_index(
        'idx_causal_workspace_target',
        'kg_causal_relationships',
        ['workspace_name', 'target_entity_id']
    )
    op.create_index(
        'idx_causal_valid',
        'kg_causal_relationships',
        ['workspace_name', 'valid_from', 'valid_to']
    )


def downgrade() -> None:
    """Remove causal relationships table."""
    op.drop_table('kg_causal_relationships')
