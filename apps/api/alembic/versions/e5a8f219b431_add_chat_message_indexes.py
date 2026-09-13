"""add_chat_message_indexes

Revision ID: e5a8f219b431
Revises: c6e1d278636c
Create Date: 2026-09-13 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a8f219b431'
down_revision: Union[str, None] = 'c6e1d278636c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Partial index for unread messages count and queries
    op.create_index(
        'idx_chat_messages_unread',
        'chat_messages',
        ['booking_id', 'sender_id'],
        unique=False,
        postgresql_where=sa.text('read_at IS NULL'),
    )
    # Composite index for message history chronological queries
    op.create_index(
        'idx_chat_messages_booking_created',
        'chat_messages',
        ['booking_id', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('idx_chat_messages_booking_created', table_name='chat_messages')
    op.drop_index('idx_chat_messages_unread', table_name='chat_messages')
