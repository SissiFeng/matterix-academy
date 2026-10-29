"""Learner connector routes; identity is exclusively the existing browser boundary."""

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from .auth import identify
from .connections import ConnectionRevision, ConnectionUpdate, RealRunRequest

router = APIRouter(prefix="/api/connections")


@router.get("")
def connections(request: Request, owner: str = Depends(identify)):
    return request.app.state.connections.list(owner)


@router.put("/{connection_id}")
def save(
    connection_id: UUID, data: ConnectionUpdate, request: Request, owner: str = Depends(identify)
):
    return request.app.state.connections.save(owner, connection_id, data)


@router.get("/{connection_id}")
def get(connection_id: UUID, request: Request, owner: str = Depends(identify)):
    return request.app.state.connections.get(owner, connection_id)


@router.post("/{connection_id}/pairing")
def pairing(
    connection_id: UUID, data: ConnectionRevision, request: Request, owner: str = Depends(identify)
):
    return request.app.state.connections.pairing(owner, connection_id, data)


@router.post("/{connection_id}/revoke")
def revoke(
    connection_id: UUID, data: ConnectionRevision, request: Request, owner: str = Depends(identify)
):
    return request.app.state.connections.revoke(owner, connection_id, data)


@router.get("/{connection_id}/preflight")
def preflight(
    connection_id: UUID, session_id: UUID, request: Request, owner: str = Depends(identify)
):
    return request.app.state.connections.preflight(owner, connection_id, session_id)


@router.post("/{connection_id}/runs")
def submit(
    connection_id: UUID, data: RealRunRequest, request: Request, owner: str = Depends(identify)
):
    return request.app.state.connections.submit(owner, connection_id, data)


@router.get("/{connection_id}/runs/{run_id}")
def run(connection_id: UUID, run_id: UUID, request: Request, owner: str = Depends(identify)):
    return request.app.state.connections.get_run(owner, connection_id, run_id)


@router.post("/{connection_id}/runs/{run_id}/stop")
def stop(
    connection_id: UUID,
    run_id: UUID,
    data: ConnectionRevision,
    request: Request,
    owner: str = Depends(identify),
):
    return request.app.state.connections.stop(owner, connection_id, run_id, data)
