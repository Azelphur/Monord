"""Update pokemon fields

Revision ID: 42772ba80b82
Revises: 0831d0428f69
Create Date: 2019-03-23 10:58:18.416004

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '42772ba80b82'
down_revision = '0831d0428f69'
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('pokemon', sa.Column('form', sa.Integer(), nullable=True))
    op.add_column('pokemon', sa.Column('pokedex_id', sa.Integer(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('pokemon', 'pokedex_id')
    op.drop_column('pokemon', 'form')
    # ### end Alembic commands ###
