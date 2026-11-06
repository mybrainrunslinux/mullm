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


def test_optional_deadline_and_required_wait_are_server_owned(client, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(factory_api.time, 'time', lambda: clock[0])
    base = {'agent_id': 'test', 'summary': 'Choose layout', 'options': ['A', 'B', 'C']}
    optional = client.post('/api/agents/blocked', json={**base, 'mode': 'optional', 'timeout_seconds': 2}).json()['session_id']
    required = client.post('/api/agents/blocked', json=base).json()['session_id']
    assert client.post('/api/agents/blocked', json={**base, 'timeout_seconds': 1}).status_code == 422
    clock[0] += 3
    # No browser timer or submission runs. A worker poll resolves the default.
    card = client.get('/api/sessions/' + optional).json()
    assert card['choice'] == 'A' and card['resolved_by'] == 'default'
    assert client.post('/api/sessions/' + optional + '/unblock', json={'choice': 'B'}).status_code == 409
    clock[0] += 999999
    assert not client.get('/api/sessions/' + required).json()['resolved']
    assert client.post('/api/sessions/' + required + '/unblock', json={'choice': 'C'}).status_code == 200


def test_notification_retry_deduplicates_successful_targets_and_excludes_prompt(client):
    from router.factory_notify import deliver_one
    import json
    card = client.post('/api/agents/blocked', json={'agent_id': 'test', 'summary': 'PRIVATE PROMPT'}).json()['session_id']
    targets = [{'url': 'https://one.example'}, {'url': 'https://two.example'}]
    calls = []
    def sender(target, event):
        assert 'PRIVATE PROMPT' not in json.dumps(event)
        calls.append(target['url'])
        return target['url'].endswith('one.example')
    assert deliver_one(targets, sender)
    with factory_api.database() as db:
        db.execute('UPDATE notifications SET available=0,lease_until=0')
    assert deliver_one(targets, lambda target, event: calls.append(target['url']) or True)
    assert calls == ['https://one.example', 'https://two.example', 'https://two.example']
    assert not deliver_one(targets, lambda *_: pytest.fail('Already sent'))
    waiting = client.post('/api/agents/blocked', json={'agent_id': 'test', 'summary': 'cancel me'}).json()['session_id']
    client.post('/api/sessions/' + waiting + '/unblock', json={'choice': 'Stop'})
    assert deliver_one(targets, lambda *_: pytest.fail('Resolved request must not send'))
    assert client.get('/api/sessions/' + card).json()['resolved'] is False
