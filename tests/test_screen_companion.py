import asyncio
import base64
import io
import json
import uuid

import httpx
import pytest
from PIL import Image

from server.screen_companion import ScreenBudget, ScreenCompanion, image_from_frame
from server.storage import DEFAULTS
from server.systemone import SCREEN_INTENTS, SCREEN_QUESTIONS, screen_questions, InitiativeDecision, ScreenDecision, SystemOneClient
from server.systemone_providers import ARK_MODEL

STREAM = str(uuid.uuid4())
STRONG = InitiativeDecision(.98, .01, 'comment')


@pytest.mark.asyncio
async def test_sampling_lifetime_is_authorized_share_not_decision_generation():
    c, _, _, _, _ = await make(screen_companion_interval_ms=1000)
    samples = []
    arrived = asyncio.Event()
    async def sample(event):
        samples.append(event)
        arrived.set()
    c.on_sample = sample
    await c.activate({'active': True, 'stream_id': STREAM})
    sampler = c.sample_task
    c.cancel_pending()  # Speech invalidates an observation, not the display grant.
    try:
        await asyncio.wait_for(arrived.wait(), 2)
        assert samples == [{'type': 'voice.screen.sample', 'stream_id': STREAM}]
        assert not await c.activate({'active': False, 'stream_id': str(uuid.uuid4())})
        assert c.sample_task is sampler
        assert await c.activate({'active': False, 'stream_id': STREAM})
        await asyncio.sleep(0)
        assert sampler.done() and c.sample_task is None
        await c.activate({'active': True, 'stream_id': STREAM})
        sampler = c.sample_task
    finally:
        await c.close()
    assert sampler.done() and not c.sample_tasks
    assert not await c.activate({'active': True, 'stream_id': STREAM})


def ambiguous_purpose_payload(*, probabilities=None, confidence=.4709962195, desire=.9999785551, must_wait=.0008040859):
    probabilities = probabilities or {'wait': .00009, 'warn': .00066, 'cheer': .38576, 'comment': .56128, 'empathize': .05221}
    return {'model': ARK_MODEL, 'answers': {
        'speak_now': {'type': 'noul', 'noul': desire},
        'must_wait': {'type': 'noul', 'noul': must_wait},
        'intent': {'type': 'choice', 'choice': max(probabilities, key=probabilities.get),
                   'confidence': confidence, 'probabilities': probabilities}}}


@pytest.mark.asyncio
@pytest.mark.parametrize('probabilities,expected', [
    (None, 'comment'),
    ({'wait': .7, 'comment': .1, 'cheer': .1, 'warn': .05, 'empathize': .05}, 'wait'),
    ({'wait': .45, 'comment': .46, 'cheer': .03, 'warn': .03, 'empathize': .03}, None),
])
async def test_screen_purpose_ambiguity_does_not_veto_strong_non_wait_evidence(probabilities, expected):
    payload = ambiguous_purpose_payload(probabilities=probabilities)
    client = SystemOneClient({'systemone_provider': 'ark', 'systemone_ark_api_key': 'fixture'},
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    try:
        decision = await client.decide(frame()['data'], [], 3)
        assert isinstance(decision, ScreenDecision) and decision.intent == expected
        assert decision.intent_confidence < client.confidence
        assert decision.non_wait_probability == pytest.approx(1 - payload['answers']['intent']['probabilities']['wait'])
        # Affect and speech-interruption choices keep their original strict gate.
        assert client.confident_choice(payload['answers']['intent']) is None
    finally:
        await client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('desire,must_wait,reason', [(.2, .001, 'low_desire'), (.999, .8, 'must_wait')])
async def test_ambiguous_purpose_never_bypasses_desire_or_privacy_wait(desire, must_wait, reason):
    payload = ambiguous_purpose_payload(desire=desire, must_wait=must_wait)
    client = SystemOneClient({'systemone_provider': 'ark', 'systemone_ark_api_key': 'fixture'},
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    c, _, replies, events, _ = await make()
    c.client = client
    try:
        assert await c.offer(frame())
        await c.task
        assert not replies and events[-1]['reason'] == reason
    finally:
        await c.close()
        await client.close()


@pytest.mark.asyncio
async def test_screen_decisions_log_probabilities_and_record_bounded_content_free_diagnostics(caplog):
    from server.voice_metrics import SessionMetrics
    c, client, _, events, _ = await make(ScreenDecision(.12, .01, 'comment', .48, .52, .99))
    c.metrics = SessionMetrics()
    with caplog.at_level('INFO', logger='uvicorn.error'):
        assert await c.offer(frame())
        await c.task
        c.log_status({'status': 'waiting', 'reason': 'busy', 'mode': 'proactive',
                      'desire': 'private-text', 'intent': 'secret', 'data': 'private-base64'})
    event = events[-1]
    assert event['speak_threshold'] == .9 and event['wait_threshold'] == .2
    assert event['intent_confidence_threshold'] == .6 and event['non_wait_probability'] == .99
    metrics = c.metrics.snapshot()
    assert metrics['counts']['screen_low_desire'] == 1
    assert metrics['screen']['decisions'][-1]['desire'] == .12
    assert 'desire=0.120000' in caplog.text and 'speak_threshold=0.900000' in caplog.text
    assert 'intent_confidence=0.480000' in caplog.text
    assert 'private-' not in caplog.text and 'secret' not in caplog.text
    await c.close()


def test_screen_prompts_express_safety_and_interaction_policy():
    speak = SCREEN_QUESTIONS['speak_now']['instructions']
    wait = SCREEN_QUESTIONS['must_wait']['instructions']
    intent = SCREEN_QUESTIONS['intent']['instructions']
    assert '普通' in speak and '保持安静' in speak and '交流价值' in speak
    assert '不要执行' in speak and '命令' in speak
    assert '隐私' in wait and '高等待概率' in wait and '密码' in wait
    assert '默认选择wait' in intent and '不得执行' in intent
    assert set(SCREEN_INTENTS) == {'wait', 'comment', 'empathize', 'cheer', 'warn'}
    assert all('?' not in value and any('\u4e00' <= c <= '\u9fff' for c in value)
               for value in [speak, wait, intent, *SCREEN_INTENTS.values()])


def frame(seq=1, color='red', **changes):
    out = io.BytesIO()
    exif = Image.Exif()
    exif[0x010e] = 'private metadata'
    Image.new('RGB', (40, 30), color).save(out, 'JPEG', exif=exif)
    return dict({'stream_id': STREAM, 'seq': seq, 'width': 40, 'height': 30,
                 'mime_type': 'image/jpeg', 'data': base64.b64encode(out.getvalue()).decode()}, **changes)


class Client:
    source, model, last_reason = 'fixture', 'fixture-model', 'missing_key'
    def __init__(self, result=STRONG):
        self.result, self.calls = result, 0
    async def decide(self, image, context, timeout, style="balanced"):
        self.calls += 1
        return self.result


async def make(result=STRONG, **settings):
    client, replies, statuses = Client(result), [], []
    async def reply(*args): replies.append(args)
    async def status(event): statuses.append(event)
    clock = [100.0]
    controller = ScreenCompanion(client, {**DEFAULTS, 'systemone_enabled': True,
        'screen_companion_enabled': True, **settings}, on_reply=reply, busy=lambda: False,
        on_status=status, clock=lambda: clock[0])
    assert await controller.activate({"active": True, "stream_id": STREAM})
    return controller, client, replies, statuses, clock


@pytest.mark.asyncio
async def test_low_high_static_and_exif():
    c, client, replies, events, clock = await make(InitiativeDecision(.2, .8, 'wait'))
    assert await c.offer(frame())
    await c.task
    assert client.calls == 1 and not replies
    assert events[-1]['reason'] == 'low_desire' and 'data' not in str(events)
    clock[0] += 3
    assert not await c.offer(frame(2)) and client.calls == 1
    client.result = STRONG
    assert await c.offer(frame(3, 'blue'))
    await c.task
    image, intent, generation, maxchars = replies[0]
    assert intent == 'comment' and c.valid(generation) and maxchars == 64
    with Image.open(io.BytesIO(base64.b64decode(image['data']))) as clean:
        assert clean.size == (40, 30) and not clean.getexif()
    assert len(replies) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('intent,accepted', [
    ('wait', False), ('comment', True), ('empathize', True),
    ('cheer', True), ('warn', True), ('correct', False),
])
async def test_only_screen_intents_can_trigger_reply(intent, accepted):
    controller, _, replies, _, _ = await make(InitiativeDecision(.98, .01, intent))
    assert await controller.offer(frame())
    await controller.task
    assert bool(replies) is accepted
    await controller.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('desire,must_wait,intent,reason,accepted', [
    (.5, .01, 'comment', 'strong_desire', True),
    (.4999, .01, 'comment', 'low_desire', False),
    (.6, .21, 'comment', 'must_wait', False),
    (.6, .01, 'wait', 'wait_intent', False),
])
async def test_lower_speak_threshold_is_used_without_bypassing_wait(desire, must_wait, intent, reason, accepted):
    c, _, replies, events, _ = await make(InitiativeDecision(desire, must_wait, intent),
                                         screen_companion_speak_threshold=.5)
    try:
        assert await c.offer(frame())
        await c.task
        assert bool(replies) is accepted
        assert events[-1]['reason'] == reason
        assert events[-1]['speak_threshold'] == .5
    finally:
        await c.close()


@pytest.mark.asyncio
async def test_missing_key_failure_and_busy_do_not_reply():
    c, client, replies, events, clock = await make(None)
    c.busy = lambda: True
    assert not await c.offer(frame()) and not client.calls
    c.busy = lambda: False
    assert await c.offer(frame())
    await c.task
    assert client.calls == 1
    assert events[-1]['reason'] == 'missing_key' and not replies
    clock[0] += 3
    async def fail(*args): raise RuntimeError('secret')
    client.decide = fail
    assert await c.offer(frame(2, 'blue'))
    await c.task
    assert events[-1]['reason'] == 'error' and 'secret' not in str(events)
    assert len(c.budget.judgments) == 2


@pytest.mark.asyncio
async def test_budget_cooldown_and_initiative_shared_state():
    c, client, replies, events, clock = await make(screen_companion_max_judgments_per_hour=1)
    assert await c.offer(frame())
    await c.task
    clock[0] += 31
    assert not await c.offer(frame(2, 'blue')) and client.calls == 1
    await asyncio.sleep(0)
    assert events[-1]['reason'] == 'budget'
    c, client, replies, events, clock = await make()
    c.budget.mark_reply(clock[0])
    assert not await c.offer(frame()) and not client.calls
    await asyncio.sleep(0)
    assert events[-1]['reason'] == 'cooldown'


@pytest.mark.asyncio
async def test_cancel_stop_singleflight_and_generation():
    c, client, replies, events, clock = await make()
    entered = asyncio.Event()
    async def wait(*args):
        entered.set()
        await asyncio.Event().wait()
    client.decide = wait
    assert await c.offer(frame())
    task = c.task
    await entered.wait()
    assert not await c.offer(frame(2, 'blue'))
    generation = c.generation
    assert await c.activate({"active": False, "stream_id": STREAM}) and not c.valid(generation)
    assert not await task and not replies and len(c.budget.judgments) == 1
    assert not await c.offer(frame(3))
    assert not await c.activate({'active': True, 'stream_id': 'not-a-uuid'})


@pytest.mark.parametrize('changes', [
    {'data': 'not-base64'}, {'data': 'data:image/jpeg;base64,AAAA'}, {'width': 41},
    {'width': 961}, {'height': 541}, {'seq': True}, {'mime_type': 'image/png'},
    {'data': base64.b64encode(b'x' * (256 * 1024 + 1)).decode()},
])
def test_invalid_images(changes):
    with pytest.raises(ValueError): image_from_frame(frame(**changes))


@pytest.mark.asyncio
@pytest.mark.parametrize('provider', ['ark', 'tokentosea'])
async def test_systemone_image_contract_and_strict_probabilities(provider):
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        probs = {key: int(key == 'comment') for key in SCREEN_INTENTS}
        answers = {'speak_now': {'type': 'noul', 'noul': .98},
                   'must_wait': {'type': 'noul', 'noul': .01},
                   'intent': {'type': 'choice', 'choice': 'comment', 'confidence': .95, 'probabilities': probs}}
        return httpx.Response(200, json={'model': ARK_MODEL if provider == 'ark' else 'clef-omni', 'answers': answers})
    client = SystemOneClient({'systemone_provider': provider, 'systemone_ark_api_key': 'key', 'systemone_api_key': 'key'}, transport=httpx.MockTransport(handler))
    try:
        data = frame()['data']
        assert await client.decide(data, [], 3) == ScreenDecision(.98, .01, 'comment', .95, 1, 1)
        body = requests[0]
        if provider == 'ark':
            assert body['state'][1] == {'type': 'image', 'image_url': 'data:image/jpeg;base64,' + data}
        else:
            assert body['images'] == [{'content_type': 'image/jpeg', 'base64': data}]
        assert set(body['questions']) == {'speak_now', 'must_wait', 'intent'}
        assert body['questions'] == screen_questions('balanced')
        assert body['state'][0]['text']['task'] == '判断屏幕是否值得主动交流' if provider == 'ark' else body['state']['task'] == '判断屏幕是否值得主动交流'
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_real_client_no_key_fails_closed():
    c, _, replies, events, clock = await make()
    c.client = SystemOneClient({'systemone_provider': 'ark', 'systemone_ark_api_key': ''})
    try:
        assert await c.offer(frame())
        await c.task
        assert not replies
        assert events[-1]['reason'] == 'missing_key'
    finally:
        await c.client.close()

@pytest.mark.asyncio
async def test_stale_decision_ignored_even_if_provider_swallows_cancel():
    c, client, replies, _, _ = await make()
    entered = asyncio.Event()
    async def stubborn(*args):
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return STRONG
    client.decide = stubborn
    assert await c.offer(frame())
    task = c.task
    await entered.wait()
    assert await c.activate({"active": False, "stream_id": STREAM})
    assert not await task and not replies


@pytest.mark.asyncio
async def test_stop_cancels_reply_callback():
    c, _, replies, _, _ = await make()
    entered = asyncio.Event()
    async def reply(*args):
        entered.set()
        await asyncio.Event().wait()
        replies.append(args)
    c.on_reply = reply
    assert await c.offer(frame())
    task = c.task
    await entered.wait()
    await c.activate({"active": False, "stream_id": STREAM})
    assert not await task and not replies


@pytest.mark.asyncio
@pytest.mark.parametrize('bad', [float('nan'), -0.1, 1.1, True])
async def test_invalid_provider_probability_fails_closed(bad):
    def handler(request):
        answers = {'speak_now': {'type': 'noul', 'noul': bad},
                   'must_wait': {'type': 'noul', 'noul': .01},
                   'intent': {'type': 'choice', 'choice': 'comment', 'confidence': .95,
                              'probabilities': {key: int(key == 'comment') for key in SCREEN_INTENTS}}}
        # httpx JSON encoder disallows NaN; encode deliberately as an invalid provider response.
        return httpx.Response(200, content=json.dumps({'model': ARK_MODEL, 'answers': answers}))
    client = SystemOneClient({'systemone_provider': 'ark', 'systemone_ark_api_key': 'key'}, transport=httpx.MockTransport(handler))
    try:
        assert await client.decide(frame()['data'], [], 3) is None
        assert client.last_reason == 'invalid_response'
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_offer_returns_before_provider_and_cancel_before_task_runs():
    c, client, replies, events, clock = await make()
    entered = asyncio.Event()
    async def waiting(*args):
        entered.set()
        await asyncio.Event().wait()
    client.decide = waiting
    assert await c.offer(frame())
    assert not entered.is_set()
    c.cancel_pending()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert c.task is None and not replies
    clock[0] += 3
    assert await c.offer(frame(2, 'blue'))
    await entered.wait()
    await c.close()
    assert c.task is None and not c.valid(c.generation)
    assert not await c.offer(frame(3))

@pytest.mark.asyncio
async def test_generation_validity_depends_on_stream_generation_and_ttl_only():
    c, client, replies, events, clock = await make()
    assert await c.offer(frame())
    await c.task
    generation = replies[0][2]
    c.busy = lambda: True
    c.budget.mark_reply(clock[0])
    assert c.valid(generation)
    clock[0] += 3.01
    assert not c.valid(generation)
    await c.close()


@pytest.mark.asyncio
async def test_unchanged_scene_is_reassessed_after_refresh_and_busy_frame_can_retry():
    c, client, replies, events, clock = await make(InitiativeDecision(.1, .1, 'wait'))
    c.busy = lambda: True
    assert not await c.offer(frame())
    await asyncio.sleep(0)
    assert events[-1]['reason'] == 'busy' and events[-1]['frames'] == 1
    c.busy = lambda: False
    assert await c.offer(frame(2)); await c.task
    clock[0] += 3
    assert not await c.offer(frame(3))
    clock[0] += 12
    assert await c.offer(frame(4)); await c.task
    assert client.calls == 2 and not replies
    assert events[-1]['judgments'] == 2 and events[-1]['frames'] == 4
    await c.close()


@pytest.mark.asyncio
async def test_timeout_at_expiry_still_reports_diagnostics_and_retains_share():
    c, client, replies, events, clock = await make()
    async def timeout(*args):
        clock[0] += 3.01
        raise TimeoutError
    client.decide = timeout
    assert await c.offer(frame()); await c.task
    assert events[-1]['status'] == 'unavailable' and events[-1]['reason'] == 'timeout'
    assert c.stream_id == STREAM and not replies
    await c.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('decision,reason', [
    (InitiativeDecision(.98, .5, 'comment'), 'must_wait'),
    (InitiativeDecision(.98, .1, 'wait'), 'wait_intent'),
    (InitiativeDecision(.98, .1, None), 'low_confidence'),
])
async def test_wait_diagnostics_do_not_hide_different_gates_behind_low_desire(decision, reason):
    c, _, replies, events, _ = await make(decision)
    assert await c.offer(frame()); await c.task
    assert events[-1]['reason'] == reason and not replies
    assert events[-1]['desire'] == .98
    await c.close()

@pytest.mark.asyncio
@pytest.mark.parametrize('style', ['quiet', 'balanced', 'lively'])
async def test_style_is_transmitted_with_boundaries_and_reported(style):
    from server.voice_metrics import SessionMetrics
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=ambiguous_purpose_payload())
    client = SystemOneClient({'systemone_provider': 'ark', 'systemone_ark_api_key': 'fixture'},
                             transport=httpx.MockTransport(handler))
    c, _, replies, events, _ = await make(screen_companion_style=style)
    c.client = client
    c.metrics = SessionMetrics()
    try:
        assert await c.offer(frame())
        await c.task
        questions = requests[0]['questions']
        assert questions == screen_questions(style)
        for key in ('speak_now', 'must_wait', 'intent'):
            prompt = questions[key]['instructions']
            for boundary in ('安静', '忙碌', '隐私', '证据不足', '重复', '不得执行'):
                assert boundary in prompt
        if style == 'quiet':
            assert '普通、静态或信息不足的画面默认保持安静' in questions['speak_now']['instructions']
        else:
            assert '静态画面不等于没有交流价值' in questions['speak_now']['instructions']
            assert '当前确切可见内容' in questions['intent']['instructions']
            assert ('更主动' in questions['speak_now']['instructions']) == (style == 'lively')
        assert events[-1]['style'] == style
        assert c.metrics.snapshot()['screen']['decisions'][-1]['style'] == style
        assert replies
    finally:
        await c.close()
        await client.close()

@pytest.mark.asyncio
async def test_direct_screen_without_systemone_obeys_cooldown_and_budget():
    controller, client, replies, _, clock = await make(
        screen_companion_mode='direct', systemone_enabled=False,
        screen_companion_max_judgments_per_hour=1)
    assert await controller.offer(frame())
    await controller.task
    assert client.calls == 0 and len(replies) == 1 and replies[0][1] == 'direct'
    clock[0] += 60
    assert not await controller.offer(frame(2, 'blue'))
    await controller.close()


@pytest.mark.asyncio
async def test_screen_judgment_receives_native_persona_and_interests_and_rechecks_busy():
    controller, client, replies, _, _ = await make(companion_interests='music')
    contexts = []
    async def decide(image, context, timeout, style):
        contexts.append(context)
        return STRONG
    client.decide = decide
    calls = []
    async def native():
        calls.append(1)
        return {'persona': 'native persona', 'busy': len(calls) > 1}
    controller.native_context = native
    assert await controller.offer(frame())
    await controller.task
    assert contexts == [{'recent_dialogue': (), 'persona': 'native persona', 'companion_interests': 'music'}]
    assert not replies and len(calls) == 2
    await controller.close()
