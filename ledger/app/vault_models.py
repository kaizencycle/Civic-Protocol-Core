"""
SQLAlchemy models for the universal Mobius Vault layer.
These tables receive writes from any authorized Mobius node
(terminal, atlas-paw, future nodes) via the vault API routes.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from .database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class VaultDeposit(Base):
    """
    Single MIC deposit event from any network node.
    Immutable — deposits are never updated, only appended.
    """

    __tablename__ = "vault_deposits"

    id = Column(Integer, primary_key=True, index=True)
    deposit_id = Column(String(128), unique=True, nullable=False, index=True)
    node_id = Column(String(64), nullable=False, index=True)
    cycle = Column(String(16), nullable=False, index=True)
    amount_mic = Column(Float, nullable=False)
    tx_hash = Column(String(256), nullable=True)
    depositor_agent = Column(String(64), nullable=True)
    cumulative_balance = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (Index("ix_vault_deposits_cycle_node", "cycle", "node_id"),)


class VaultSeal(Base):
    """
    Reserve Block seal event. Written when a node's block reaches 50 MIC
    and sentinel quorum is achieved. Immutable after creation.
    """

    __tablename__ = "vault_seals"

    id = Column(Integer, primary_key=True, index=True)
    seal_id = Column(String(128), unique=True, nullable=False, index=True)
    node_id = Column(String(64), nullable=False, index=True)
    cycle = Column(String(16), nullable=False, index=True)
    block_number = Column(Integer, nullable=False)
    seal_hash = Column(String(256), nullable=False)
    sentinel_quorum = Column(Text, nullable=True)  # JSON: agent list
    attestations_count = Column(Integer, default=0)
    immortalized = Column(Boolean, default=False, nullable=False)
    substrate_event_hash = Column(String(256), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    immortalized_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("node_id", "block_number", name="uq_seal_node_block"),
        Index("ix_vault_seals_cycle_node", "cycle", "node_id"),
    )


class VaultAttestation(Base):
    """
    Individual sentinel agent attestation for a pending seal.
    Quorum = 5 attestations from distinct agents.
    """

    __tablename__ = "vault_attestations"

    id = Column(Integer, primary_key=True, index=True)
    seal_id = Column(String(128), nullable=False, index=True)
    agent = Column(String(32), nullable=False)
    cycle = Column(String(16), nullable=False)
    node_id = Column(String(64), nullable=False)
    signature = Column(String(256), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("seal_id", "agent", name="uq_attest_seal_agent"),
    )
