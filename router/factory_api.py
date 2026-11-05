"""Durable factory run events and human decisions shared by visualizations and agents."""
from __future__ import annotations
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from typing import Literal
from urllib.parse import parse_qs, urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from router.config import settings

def require_same_origin(request: Request):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and urlsplit(origin).netloc.lower() != request.headers.get('host', '').lower()):
            raise HTTPException(403, 'Cross-origin control requests are not allowed')

router = APIRouter(dependencies=[Depends(require_same_origin)])

@contextmanager
def database():
    path = settings.cache_dir / 'factory.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    db.executescript('''
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, updated REAL, payload TEXT);
        CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, created REAL, payload TEXT);
        CREATE INDEX IF NOT EXISTS events_run ON events(run_id, sequence);
        CREATE TABLE IF NOT EXISTS lease_waiters(run_id TEXT PRIMARY KEY, requested REAL, seen REAL);
        CREATE TABLE IF NOT EXISTS leases(id TEXT PRIMARY KEY, run_id TEXT, expires REAL);
        CREATE TABLE IF NOT EXISTS cards(id TEXT PRIMARY KEY, created REAL, payload TEXT, choice TEXT, resolved REAL, dismissed INTEGER DEFAULT 0);
    ''')
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()

class RunSnapshot(BaseModel):
    run_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,100}$')
    snapshot: dict

@router.post('/api/factory/runs')
def publish_run(body: RunSnapshot):
    payload = dict(body.snapshot, run_id=body.run_id)
    encoded = json.dumps(payload)
    if len(encoded.encode()) > 256_000:
        raise HTTPException(413, 'Run snapshot exceeds 256 KB')
    with database() as db:
        db.execute('INSERT INTO runs VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated,payload=excluded.payload', (body.run_id,time.time(),encoded))
        cur = db.execute('INSERT INTO events(run_id,created,payload) VALUES(?,?,?)', (body.run_id,time.time(),encoded))
        if payload.get('status') in ('accepted', 'stopped', 'failed', 'cancelled', 'rejected'):
            db.execute('DELETE FROM lease_waiters WHERE run_id=?', (body.run_id,))
            db.execute('DELETE FROM leases WHERE run_id=?', (body.run_id,))
            for card in db.execute('SELECT id,payload FROM cards WHERE resolved IS NULL').fetchall():
                data = json.loads(card['payload'])
                if data.get('run_id') == body.run_id:
                    data['resolved_by'] = 'system'
                    db.execute('UPDATE cards SET resolved=?,choice=?,payload=? WHERE id=?',
                               (time.time(), 'Run ended: ' + payload['status'], json.dumps(data), card['id']))
        return {'sequence': cur.lastrowid}

@router.get('/api/factory/runs')
def list_runs():
    with database() as db:
        rows = db.execute('SELECT * FROM runs ORDER BY updated DESC LIMIT 100').fetchall()
    return {'runs': [dict(json.loads(row['payload']), updated_at=row['updated']) for row in rows]}

@router.get('/api/factory/runs/{run_id}/events')
def run_events(run_id: str, after: int = 0):
    with database() as db:
        rows = db.execute('SELECT * FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT 200', (run_id,after)).fetchall()
    return {'events': [{'sequence': row['sequence'], 'created_at': row['created'], 'snapshot': json.loads(row['payload'])} for row in rows]}

class ReviewLink(BaseModel):
    label: str = Field(max_length=100)
    url: str = Field(pattern=r'^https?://', max_length=2000)

class BlockedCard(BaseModel):
    agent_id: str = Field(max_length=150)
    agent_type: str = Field(default='factory', max_length=100)
    parent_id: str = Field(default='', max_length=150)
    run_id: str = Field(default='', max_length=150)
    task_id: str = Field(default='', max_length=150)
    block_reason: str = Field(default='needs_human', max_length=200)
    summary: str = Field(min_length=1, max_length=8000)
    context: str = Field(default='', max_length=8000)
    links: list[ReviewLink] = Field(default_factory=list, max_length=5)
    options: list[str] = Field(default_factory=lambda: ['Retry', 'Stop'], min_length=1, max_length=12)
    severity: Literal['low','medium','high','critical'] = 'medium'

@router.post('/api/agents/blocked')
def create_card(body: BlockedCard):
    if any(not option or len(option) > 500 for option in body.options):
        raise HTTPException(422, 'Invalid option')
    session_id = 'agent-' + uuid.uuid4().hex
    with database() as db:
        db.execute('INSERT INTO cards(id,created,payload) VALUES(?,?,?)', (session_id,time.time(),body.model_dump_json()))
    return {'session_id': session_id, 'status': 'needs_human'}

def card_payload(row):
    payload = json.loads(row['payload'])
    resolved = row['resolved'] is not None
    return dict(payload, session_id=row['id'], request_id=row['id'], created_at=row['created'],
                elapsed_s=round((row['resolved'] or time.time())-row['created']),
                resolved=resolved, resolved_choice=row['choice'], choice=row['choice'],
                color='green' if resolved else ('red' if payload['severity'] in ('high','critical') else 'orange'),
                status='resolved' if resolved else 'needs_human', tier='local')

@router.get('/api/sessions')
def list_cards():
    with database() as db:
        rows = db.execute('SELECT * FROM cards WHERE dismissed=0 ORDER BY resolved IS NOT NULL,created DESC LIMIT 200').fetchall()
    cards = [card_payload(row) for row in rows]
    return {'sessions': cards, 'count': len(cards)}

@router.get('/api/sessions/{session_id}')
def get_card(session_id: str):
    with database() as db:
        row = db.execute('SELECT * FROM cards WHERE id=?', (session_id,)).fetchone()
    if row is None: raise HTTPException(404, 'Unknown human request')
    return card_payload(row)

@router.post('/api/sessions/{session_id}/unblock')
async def answer_card(session_id: str, request: Request):
    raw = await request.body()
    if len(raw) > 16_000: raise HTTPException(413, 'Decision too large')
    try:
        if 'application/json' in request.headers.get('content-type',''):
            choice = json.loads(raw).get('choice','')
        else:
            choice = parse_qs(raw.decode()).get('choice',[''])[0]
    except (ValueError, AttributeError, UnicodeDecodeError):
        raise HTTPException(422, 'Invalid decision')
    if not isinstance(choice,str) or not choice.strip() or len(choice)>8000:
        raise HTTPException(422, 'A human decision is required')
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM cards WHERE id=?', (session_id,)).fetchone()
        if row is None: raise HTTPException(404, 'Unknown human request')
        if row['resolved'] is not None:
            if row['choice'] != choice: raise HTTPException(409, 'This request already has a decision')
        else:
            db.execute('UPDATE cards SET choice=?,resolved=? WHERE id=?', (choice,time.time(),session_id))
    return {'session_id':session_id,'choice':choice,'status':'resolved'}

@router.post('/api/sessions/{session_id}/dismiss')
def dismiss_card(session_id: str):
    with database() as db:
        row = db.execute('SELECT resolved FROM cards WHERE id=?',(session_id,)).fetchone()
        if row is None: raise HTTPException(404, 'Unknown human request')
        if row['resolved'] is None: raise HTTPException(409, 'Answer the request before dismissing it')
        db.execute('UPDATE cards SET dismissed=1 WHERE id=?',(session_id,))
    return {'dismissed': True}

@router.post('/api/factory/runs/{run_id}/interrupt')
def interrupt_run(run_id: str):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT payload FROM runs WHERE id=?',(run_id,)).fetchone()
        if row is None: raise HTTPException(404,'Unknown run')
        snapshot=json.loads(row['payload'])
        if snapshot.get('status') not in ('running','needs_human'):
            raise HTTPException(409,'Run is not active')
        pending=db.execute('SELECT * FROM cards WHERE resolved IS NULL').fetchall()
        for card in pending:
            if json.loads(card['payload']).get('run_id')==run_id:
                return {'session_id':card['id'],'status':'needs_human'}
        body = BlockedCard(agent_id='factory-'+run_id, run_id=run_id,
            summary='Operator requested a pause. The worker will stop at its next task checkpoint. Resume or stop the run.',
            block_reason='operator_interrupt',options=['Resume','Stop'])
        session_id = 'agent-' + uuid.uuid4().hex
        db.execute('INSERT INTO cards(id,created,payload) VALUES(?,?,?)', (session_id,time.time(),body.model_dump_json()))
    return {'session_id': session_id, 'status': 'needs_human'}


class LeaseRequest(BaseModel):
    run_id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,100}$')

@router.post('/api/factory/inference-lease')
def acquire_inference(body: LeaseRequest):
    with database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM leases WHERE expires < ?', (time.time(),))
        run = db.execute('SELECT payload FROM runs WHERE id=?', (body.run_id,)).fetchone()
        if run is None:
            raise HTTPException(404, 'Publish the run before requesting inference')
        if json.loads(run['payload']).get('status') != 'running':
            raise HTTPException(409, 'Only running projects can request inference')
        db.execute('DELETE FROM lease_waiters WHERE seen < ?', (time.time()-15,))
        db.execute('INSERT INTO lease_waiters VALUES(?,?,?) ON CONFLICT(run_id) DO UPDATE SET seen=excluded.seen', (body.run_id,time.time(),time.time()))
        if db.execute('SELECT id FROM leases LIMIT 1').fetchone():
            return {'acquired': False}
        first=db.execute('SELECT run_id FROM lease_waiters ORDER BY requested,run_id LIMIT 1').fetchone()
        if first['run_id'] != body.run_id:
            return {'acquired': False}
        db.execute('DELETE FROM lease_waiters WHERE run_id=?', (body.run_id,))
        lease_id=uuid.uuid4().hex
        db.execute('INSERT INTO leases VALUES(?,?,?)', (lease_id,body.run_id,time.time()+45))
        return {'acquired': True, 'lease_id': lease_id, 'expires_in': 45}

@router.delete('/api/factory/inference-lease/{lease_id}')
def release_inference(lease_id: str):
    with database() as db:
        db.execute('DELETE FROM leases WHERE id=?',(lease_id,))
    return {'released': True}
