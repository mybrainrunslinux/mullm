from unittest.mock import Mock

import pytest

from router import config


@pytest.fixture
def startup(monkeypatch, tmp_path):
    import router.main as main
    monkeypatch.setattr(config, 'load_toml_config', lambda: {})
    monkeypatch.delenv('MULLM_AUTO_GENERATE_CERT', raising=False)
    settings = config.Settings(_env_file=None, cache_dir=tmp_path / 'cache',
                               ssl_certfile=None, ssl_keyfile=None, remote_access=False,
                               dev_mode=True, mtls_enabled=False, port=6856)
    monkeypatch.setattr(main, 'settings', settings)
    monkeypatch.setattr(config, 'settings', settings)
    monkeypatch.setattr(main, '_is_first_run', lambda: True)
    monkeypatch.setattr(main, '_local_ips', lambda: [])
    monkeypatch.setenv('MULLM_OPEN_BROWSER', '0')
    run = Mock()
    monkeypatch.setattr('uvicorn.run', run)
    return main, settings, run


@pytest.mark.parametrize('old_certificates', [False, True])
def test_desktop_startup_never_enables_tls_from_cached_certificates(startup, old_certificates, capsys):
    main, settings, run = startup
    certs = settings.cache_dir / 'certs'
    if old_certificates:
        certs.mkdir(parents=True)
        (certs / 'mullm.crt').write_text('old self-signed certificate')
        (certs / 'mullm.key').write_text('old key')
    main.serve()
    assert settings.auto_generate_cert is False
    assert run.call_args.kwargs['host'] == '127.0.0.1'
    assert 'ssl_certfile' not in run.call_args.kwargs
    assert 'http://127.0.0.1:6856/setup' in capsys.readouterr().out
    assert config.local_server_url() == 'http://127.0.0.1:6856'
    if not old_certificates:
        assert not certs.exists()


def test_explicit_https_is_preserved_and_clients_use_same_url(startup):
    main, settings, run = startup
    settings.ssl_certfile = '/explicit/cert.pem'
    settings.ssl_keyfile = '/explicit/key.pem'
    settings.port = 7777
    main.serve()
    assert run.call_args.kwargs['ssl_certfile'] == settings.ssl_certfile
    assert config.local_server_url() == 'https://127.0.0.1:7777'


def test_incomplete_explicit_tls_fails_instead_of_silently_using_http(startup):
    main, settings, run = startup
    settings.ssl_certfile = '/explicit/cert.pem'
    with pytest.raises(RuntimeError, match='both MULLM_SSL_CERTFILE'):
        main.serve()
    run.assert_not_called()


def test_plain_mullm_starts_the_app(monkeypatch, startup):
    from router import cli
    main, settings, run = startup
    monkeypatch.setattr('sys.argv', ['mullm'])
    cli.main()
    run.assert_called_once()


@pytest.mark.parametrize('first_run,path', [(True, '/setup'), (False, '/chat')])
def test_interactive_start_opens_http_in_browser(monkeypatch, startup, first_run, path):
    main, settings, run = startup
    monkeypatch.setenv('MULLM_OPEN_BROWSER', '1')
    monkeypatch.setattr(main, '_is_first_run', lambda: first_run)
    timer = Mock()
    monkeypatch.setattr('threading.Timer', timer)
    main.serve()
    assert timer.call_args.kwargs['args'] == ('http://127.0.0.1:6856' + path,)
    timer.return_value.start.assert_called_once()


def test_help_explains_how_to_start_without_starting(monkeypatch, startup, capsys):
    from router import cli
    main, settings, run = startup
    monkeypatch.setattr('sys.argv', ['mullm', '--help'])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 0
    assert 'After installation, run mullm' in capsys.readouterr().out
    run.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('results,code', [
    ([{'status': 'done', 'verified': True}], 0),
    ([{'status': 'done', 'verified': False}], 1),
    ([{'status': 'failed'}], 1),
    ([{'status': 'pending'}], 1),
    ([], 1),
])
async def test_harness_exit_status_reflects_results(monkeypatch, results, code):
    from argparse import Namespace
    from unittest.mock import AsyncMock
    from router import cli, orchestrator
    orch = Mock()
    orch.plan_from_tasks = AsyncMock(return_value=object())
    orch.execute = AsyncMock(return_value=results)
    monkeypatch.setattr(orchestrator, 'Orchestrator', lambda **kwargs: orch)
    args = Namespace(self_update=False, apply=False, server_url='http://127.0.0.1:6856',
                     verify='', timeout=60, orchestrate='test task', dry_run=False,
                     code=True, cost_optimize=False, no_tdd=False, bugfix_tdd=False,
                     onefile=False, target_file='')
    assert await cli._orchestrate_from_cli(args) == code
