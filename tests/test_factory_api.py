from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from router import factory_api

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(factory_api.settings, 'cache_dir', tmp_path)
    app = FastAPI()
    app.include_router(factory_api.router)
    with TestClient(app) as client:
        yield client

def test_run_history_and_human_decision_survive_reconnect(client):
    for state in ('running','needs_human'):
        assert client.post('/api/factory/runs', json={'run_id':'test-run','snapshot':{'status':state}}).status_code == 200
    history=client.get('/api/factory/runs/test-run/events').json()['events']
    assert [e['snapshot']['status'] for e in history] == ['running','needs_human']
    assert len(client.get('/api/factory/runs/test-run/events',params={'after':history[0]['sequence']}).json()['events']) == 1
    card=client.post('/api/agents/blocked',json={'agent_id':'test','run_id':'test-run','summary':'Need <human> "input"','options':['Retry','Stop']}).json()
    path='/api/sessions/'+card['session_id']
    assert client.get(path).json()['resolved'] is False
    assert client.post(path+'/dismiss').status_code == 409
    assert client.post(path+'/unblock',json={'choice':''}).status_code == 422
    assert client.post(path+'/unblock',data={'choice':'Retry'}).json()['choice'] == 'Retry'
    assert client.get(path).json()['resolved_choice'] == 'Retry'
    assert client.post(path+'/unblock',json={'choice':'Retry'}).status_code == 200
    assert client.post(path+'/unblock',json={'choice':'Stop'}).status_code == 409
    assert client.post(path+'/dismiss').status_code == 200
    assert client.get('/api/sessions').json()['count'] == 0
    # The decision remains in the durable ledger after the card is dismissed.
    assert client.get(path).json()['choice'] == 'Retry'

def test_interrupt_creates_one_actionable_card_and_cannot_interrupt_finished_run(client):
    client.post('/api/factory/runs',json={'run_id':'run','snapshot':{'status':'running'}})
    first=client.post('/api/factory/runs/run/interrupt').json()
    assert client.post('/api/factory/runs/run/interrupt').json()['session_id'] == first['session_id']
    card=client.get('/api/sessions/'+first['session_id']).json()
    assert card['options'] == ['Resume','Stop']
    client.post('/api/factory/runs',json={'run_id':'run','snapshot':{'status':'accepted'}})
    assert client.post('/api/factory/runs/run/interrupt').status_code == 409

def test_cross_site_pages_cannot_submit_operator_decisions(client):
    card=client.post('/api/agents/blocked',json={'agent_id':'x','summary':'Need operator'}).json()
    path='/api/sessions/'+card['session_id']+'/unblock'
    assert client.post(path,data={'choice':'Retry'},headers={'Origin':'https://attacker.example'}).status_code == 403
    assert client.get('/api/sessions/'+card['session_id']).json()['resolved'] is False

def test_parallel_projects_share_an_expiring_fifo_inference_slot(client):
    for run in ('one','two','three'):
        client.post('/api/factory/runs',json={'run_id':run,'snapshot':{'status':'running'}})
    first=client.post('/api/factory/inference-lease',json={'run_id':'one'}).json()
    assert first['acquired']
    assert client.post('/api/factory/inference-lease',json={'run_id':'two'}).json()['acquired'] is False
    assert client.post('/api/factory/inference-lease',json={'run_id':'three'}).json()['acquired'] is False
    client.delete('/api/factory/inference-lease/'+first['lease_id'])
    assert client.post('/api/factory/inference-lease',json={'run_id':'three'}).json()['acquired'] is False
    second=client.post('/api/factory/inference-lease',json={'run_id':'two'}).json()
    assert second['acquired']
    with factory_api.database() as db:
        db.execute('UPDATE leases SET expires=0')
    assert client.post('/api/factory/inference-lease',json={'run_id':'three'}).json()['acquired']

def test_terminal_run_closes_stale_cards_without_claiming_human_approval(client):
    client.post('/api/factory/runs',json={'run_id':'done','snapshot':{'status':'running'}})
    assert client.post('/api/factory/inference-lease',json={'run_id':'done'}).json()['acquired']
    card=client.post('/api/agents/blocked',json={'agent_id':'x','run_id':'done','summary':'pause'}).json()
    client.post('/api/factory/runs',json={'run_id':'done','snapshot':{'status':'stopped'}})
    result=client.get('/api/sessions/'+card['session_id']).json()
    assert result['resolved_by']=='system'
    assert result['choice']=='Run ended: stopped'
    assert client.post('/api/factory/inference-lease',json={'run_id':'done'}).status_code == 409
    client.post('/api/factory/runs',json={'run_id':'next','snapshot':{'status':'running'}})
    assert client.post('/api/factory/inference-lease',json={'run_id':'next'}).json()['acquired']


def test_concurrent_interrupts_share_one_decision(client):
    from concurrent.futures import ThreadPoolExecutor
    client.post('/api/factory/runs',json={'run_id':'run','snapshot':{'status':'running'}})
    with ThreadPoolExecutor(max_workers=4) as workers:
        decisions=list(workers.map(lambda _: client.post('/api/factory/runs/run/interrupt').json(), range(4)))
    assert len({item['session_id'] for item in decisions}) == 1
    assert client.get('/api/sessions').json()['count'] == 1
