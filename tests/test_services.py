import json
from unittest.mock import Mock
import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import NotFound
import server
import subscriber
import cloud_log
import deploy

@pytest.fixture
def app(monkeypatch):
    store, pub = Mock(), Mock()
    store.bucket.return_value.blob.return_value.download_as_bytes.return_value = b'<html>hello</html>'
    monkeypatch.setattr(server, 'clients', lambda: (store, pub))
    monkeypatch.setenv('BUCKET_NAME', 'test-bucket')
    monkeypatch.setenv('TOPIC_PATH', 'projects/test/topics/forbidden')
    log = Mock()
    monkeypatch.setattr(server, 'emit', log)
    with TestClient(server.app) as client:
        yield client, store, pub, log

@pytest.mark.parametrize('method', ['PUT','DELETE','HEAD','CONNECT','OPTIONS','TRACE','PATCH'])
def test_methods(app, method):
    client, store, pub, log = app
    response = client.request(method, '/0.html')
    assert response.status_code == 501
    assert log.call_args.args[1] == 'ERROR'
    store.bucket.assert_not_called()
    if method == 'HEAD':
        assert response.content == b''

def test_get_post(app):
    client, store, _, _ = app
    assert client.get('/0.html').content == b'<html>hello</html>'
    for kwargs in ({'json': {'file':'0.html'}}, {'data': {'file':'0.html'}},
                   {'content':'0.html', 'headers':{'Content-Type':'text/plain'}}):
        assert client.post('/', **kwargs).status_code == 200
    store.bucket.return_value.blob.assert_called_with('0.html')

def test_missing(app):
    client, store, _, log = app
    store.bucket.return_value.blob.return_value.download_as_bytes.side_effect = NotFound('missing')
    assert client.get('/missing').status_code == 404
    assert log.call_args.args[1] == 'WARNING'

@pytest.mark.parametrize('country', ['North Korea','Iran','Cuba','Myanmar','Iraq','Libya','Sudan','Zimbabwe','Syria'])
def test_forbidden(app, country):
    client, store, pub, log = app
    assert client.get('/0.html', headers={'X-country':country}).status_code == 400
    event = json.loads(pub.publish.call_args.args[1])
    assert event['country'] == country and event['status'] == 400
    assert log.call_args.args[1] == 'CRITICAL'
    store.bucket.assert_not_called()

def test_publish_failure(app):
    client, _, pub, log = app
    pub.publish.return_value.result.side_effect = RuntimeError('offline')
    assert client.get('/0.html', headers={'X-country':'Iran'}).status_code == 503
    assert [c.args[1] for c in log.call_args_list] == ['CRITICAL','ERROR']

def test_reporter_ack_after_print(capsys):
    message = Mock(data=json.dumps({'event':'forbidden_country','event_id':'id',
                                  'country':'Iran','path':'/0.html'}).encode(), message_id='msg')
    subscriber.handle_message(message)
    assert 'Permission denied: Iran' in capsys.readouterr().out
    message.ack.assert_called_once()
    message.nack.assert_not_called()

def test_bad_event_nack():
    message = Mock(data=b'invalid', message_id='msg')
    subscriber.handle_message(message)
    message.nack.assert_called_once()
    message.ack.assert_not_called()

def test_cloud_severity(monkeypatch):
    remote = Mock()
    monkeypatch.setattr(cloud_log, 'logger', lambda: remote)
    monkeypatch.setenv('CLOUD_LOGGING','1')
    cloud_log.emit({'status':501}, 'ERROR')
    remote.log_struct.assert_called_once_with({'status':501}, severity='ERROR')

def test_startup_syntax(tmp_path):
    import subprocess
    for role in ['server','reporter']:
        script=tmp_path / (role+'.sh')
        script.write_text(deploy.startup(role, 'test-project', 'test-bucket'))
        subprocess.run(['bash','-n',str(script)],check=True)
        assert script.stat().st_size < 256*1024

@pytest.mark.parametrize('path', ['/', '/docs', '/nested/file.html'])
def test_no_automatic_options_response(app, path):
    client, _, _, log = app
    assert client.options(path).status_code == 501
    assert log.call_args.args[1] == 'ERROR'

def test_bad_and_oversized_post(app):
    client, store, _, _ = app
    assert client.post('/', content='{', headers={'Content-Type':'application/json'}).status_code == 400
    assert client.post('/', json={}).status_code == 400
    assert client.post('/', content=b'x'*65537).status_code == 413
    store.bucket.assert_not_called()
