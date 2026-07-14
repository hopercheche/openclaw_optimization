"""Strict request-model dispatch for the external-agent bridge."""

import aiohttp
import pytest

from evalscope.agent.external.bridge import ModelProxyServer
from evalscope.api.agent import EventType
from evalscope.api.model import GenerateConfig, Model, ModelOutput
from evalscope.models.mockllm import MockLLM
from evalscope.utils.function_utils import AsyncioLoopRunner


@pytest.fixture(autouse=True)
def _release_bridge_loop():
    yield
    AsyncioLoopRunner.shutdown_for_thread()


def _model(name: str, text: str) -> Model:
    api = MockLLM(
        model_name=name,
        custom_outputs=[ModelOutput.from_content(model=name, content=text)],
    )
    return Model(api=api, config=GenerateConfig())


def test_strict_bridge_dispatches_by_request_model_and_traces_resolution():
    async def _go():
        proxy = await ModelProxyServer.get_or_start()
        default = _model('default-model', 'DEFAULT')
        small = _model('resolved-small', 'SMALL')
        async with proxy.trial_session(
            model=default,
            framework='router-test',
            model_routes={'small-request': small},
            strict_model_routing=True,
        ) as session:
            headers = {'Authorization': f'Bearer {session.token}'}
            async with aiohttp.ClientSession(headers=headers) as client:
                response = await client.post(
                    f'{proxy.base_url}/openai/v1/responses',
                    json={'model': 'small-request', 'input': 'route this'},
                )
                assert response.status == 200
                payload = await response.json()

                rejected = await client.post(
                    f'{proxy.base_url}/openai/v1/responses',
                    json={'model': 'unknown', 'input': 'must fail'},
                )
                rejected_payload = await rejected.json()

            return payload, rejected.status, rejected_payload, session.recorder.snapshot()

    payload, rejected_status, rejected_payload, trace = AsyncioLoopRunner.run(_go())
    assert payload['model'] == 'small-request'
    assert rejected_status == 400
    assert rejected_payload['error']['code'] == 'unknown_model'

    model_events = [event for event in trace.events if event.type == EventType.MODEL_GENERATE]
    assert len(model_events) == 1
    assert model_events[0].payload['requested_model'] == 'small-request'
    assert model_events[0].payload['resolved_model'] == 'resolved-small'


def test_non_strict_bridge_preserves_default_model_fallback():
    async def _go():
        proxy = await ModelProxyServer.get_or_start()
        default = _model('default-model', 'DEFAULT')
        async with proxy.trial_session(model=default, framework='legacy') as session:
            async with aiohttp.ClientSession(
                headers={'Authorization': f'Bearer {session.token}'},
            ) as client:
                response = await client.post(
                    f'{proxy.base_url}/openai/v1/responses',
                    json={'model': 'unmapped-model', 'input': 'legacy fallback'},
                )
                return response.status, session.recorder.snapshot()

    status, trace = AsyncioLoopRunner.run(_go())
    assert status == 200
    event = next(event for event in trace.events if event.type == EventType.MODEL_GENERATE)
    assert event.payload['resolved_model'] == 'default-model'
