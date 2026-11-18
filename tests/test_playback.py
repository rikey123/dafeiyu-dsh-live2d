import pytest
import httpx
from pipecat.frames.frames import AggregatedTextFrame, ErrorFrame, InterruptionFrame, LLMContextFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame, OutputAudioRawFrame, TTSStartedFrame, TTSTextFrame, TTSStoppedFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.pipeline.pipeline import Pipeline
from pipecat.tests.utils import run_test

from server.playback import ConfirmedContext, PlaybackBoundary, PlaybackLedger, PlaybackStart
from server.pipecat_voice import DuckObserver
from server.voice_metrics import SessionMetrics
from speech.pipecat_services import LocalSpeechSTT, LocalSpeechTTS
from types import SimpleNamespace


def test_ack_requires_current_complete_exact_boundary_and_is_idempotent():
    saved = []
    ledger = PlaybackLedger(lambda _group, text: saved.append(text))
    turn = ledger.start("first")
    turn.samples, turn.text, turn.boundary = 480, ["你好。"], True
    valid = {"epoch": "first", "consumed_samples": 480, "sample_rate": 24000, "completed": True}
    for changes in ({"epoch": "old"}, {"consumed_samples": 481}, {"consumed_samples": True},
                    {"sample_rate": 16000}, {"completed": False}, {"consumed_samples": 479}):
        assert not ledger.acknowledge({**valid, **changes})
    assert ledger.acknowledge(valid)
    assert not ledger.acknowledge(valid)
    assert saved == ["你好。"]
    turn = ledger.start("second")
    turn.samples, turn.boundary = 480, True
    assert not ledger.acknowledge(valid)
    ledger.interrupt()
    assert not ledger.acknowledge({**valid, "epoch": "second"})


@pytest.mark.asyncio
async def test_boundary_counts_sent_output_and_waits_for_stop():
    saved, events = [], []
    ledger = PlaybackLedger(lambda _group, text: saved.append(text))
    turn = ledger.start("epoch")
    class RTVI:
        async def send_server_message(self, data):
            events.append(data)
    processor = PlaybackBoundary(ledger, RTVI())
    async def discard(frame, direction):
        pass
    processor.push_frame = discard
    await processor.process_frame(OutputAudioRawFrame(audio=b"\0\0" * 240, sample_rate=24000, num_channels=1), FrameDirection.DOWNSTREAM)
    await processor.process_frame(TTSTextFrame("你好。", text_type="sentence"), FrameDirection.DOWNSTREAM)
    assert not events and not turn.boundary
    await processor.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)
    assert events == [{"type": "voice.playback.boundary", "epoch": "epoch", "samples": 240, "sample_rate": 24000, "text": "你好。"}]


@pytest.mark.asyncio
async def test_context_excludes_unconfirmed_assistant_and_preserves_prior_history():
    initial = [{"role": "assistant", "content": "旧回复"}]
    ledger = PlaybackLedger(lambda _group, _text: None)
    processor = ConfirmedContext(ledger, initial)
    sent = []
    async def capture(frame, direction):
        sent.append(frame.context.messages)
    processor.push_frame = capture
    context = LLMContext(messages=[*initial, {"role": "user", "content": "问题"}, {"role": "assistant", "content": "未听到"}])
    await processor.process_frame(LLMContextFrame(context), FrameDirection.DOWNSTREAM)
    assert [message["content"] for message in sent[-1]] == ["旧回复", "问题"]
    assert context.messages[-1]["content"] == "未听到"
    turn = ledger.start("new")
    turn.samples, turn.text, turn.boundary = 240, ["完整回复"], True
    assert ledger.acknowledge({"epoch": "new", "consumed_samples": 240, "sample_rate": 24000, "completed": True})
    context.add_message({"role": "assistant", "content": "完整回复"})
    await processor.process_frame(LLMContextFrame(context), FrameDirection.DOWNSTREAM)
    assert [message["content"] for message in sent[-1]] == ["旧回复", "问题", "完整回复"]


@pytest.mark.asyncio
async def test_late_ack_restores_original_order_in_next_prompt():
    initial = [{"role": "assistant", "content": "旧"}]
    context = LLMContext(messages=[*initial, {"role": "assistant", "content": "已完成"}, {"role": "user", "content": "新问题"}])
    ledger = PlaybackLedger(lambda _group, _text: None)
    processor = ConfirmedContext(ledger, initial)
    sent = []
    async def capture(frame, direction):
        sent.append([message["content"] for message in frame.context.messages])
    processor.push_frame = capture
    await processor.process_frame(LLMContextFrame(context), FrameDirection.DOWNSTREAM)
    turn = ledger.start("late")
    turn.samples, turn.text, turn.boundary = 240, ["已完成"], True
    assert ledger.acknowledge({"epoch": "late", "consumed_samples": 240, "sample_rate": 24000, "completed": True})
    await processor.process_frame(LLMContextFrame(context), FrameDirection.DOWNSTREAM)
    assert sent == [["旧", "新问题"], ["旧", "已完成", "新问题"]]


@pytest.mark.asyncio
async def test_tts_error_invalidates_epoch_even_before_output_start():
    saved = []
    ledger = PlaybackLedger(lambda _group, text: saved.append(text))
    ledger.generating("epoch")
    observer = DuckObserver(SessionMetrics(), ledger)
    await observer.on_push_frame(SimpleNamespace(frame=ErrorFrame(error="TTS failed", processor=LocalSpeechTTS())))
    turn = ledger.start("epoch")
    turn.samples, turn.text, turn.boundary = 240, ["未完整合成"], True
    assert not ledger.acknowledge({"epoch": "epoch", "consumed_samples": 240, "sample_rate": 24000, "completed": True})
    assert not saved
    ledger.begin_generation()
    ledger.generating("next")
    next_turn = ledger.start("next")
    next_turn.samples, next_turn.text, next_turn.boundary = 240, ["正常"], True
    assert ledger.acknowledge({"epoch": "next", "consumed_samples": 240, "sample_rate": 24000, "completed": True})
    assert saved == ["正常"]


@pytest.mark.asyncio
async def test_non_tts_error_does_not_invalidate_playback():
    ledger = PlaybackLedger(lambda _group, _text: None)
    ledger.generating("epoch")
    turn = ledger.start("epoch")
    observer = DuckObserver(SessionMetrics(), ledger)
    await observer.on_push_frame(SimpleNamespace(frame=ErrorFrame(error="STT failed", processor=LocalSpeechSTT())))
    assert not turn.interrupted


@pytest.mark.asyncio
async def test_actual_tts_pipeline_error_after_pcm_invalidates_turn(monkeypatch):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(200, content=b"\1\0" * 160, headers={"X-Audio-Sample-Rate": "24000", "X-Audio-Channels": "1", "X-Audio-Format": "pcm_s16le"})
        return httpx.Response(500)
    native = httpx.AsyncClient
    monkeypatch.setattr("speech.pipecat_services.httpx.AsyncClient", lambda **kwargs: native(transport=httpx.MockTransport(handler), **kwargs))
    ledger = PlaybackLedger(lambda _group, _text: pytest.fail("failed audio must not be persisted"))
    class RTVI:
        async def send_server_message(self, _data):
            pass
    pipeline = Pipeline([LocalSpeechTTS(), PlaybackStart(ledger), PlaybackBoundary(ledger, RTVI())])
    downstream, upstream = await run_test(pipeline, observers=[DuckObserver(SessionMetrics(), ledger)], frames_to_send=[
        LLMFullResponseStartFrame(), LLMTextFrame("第一句。"), LLMTextFrame("第二句。"), LLMFullResponseEndFrame()])
    assert any(isinstance(frame, OutputAudioRawFrame) for frame in downstream)
    assert any(isinstance(frame, ErrorFrame) for frame in upstream)
    turn = ledger.turn
    assert turn and turn.interrupted
    assert not ledger.acknowledge({"epoch": turn.epoch, "consumed_samples": turn.samples, "sample_rate": 24000, "completed": True})


def test_sentence_ack_out_of_order_keeps_contiguous_prefix_and_groups():
    saved = {}
    ledger = PlaybackLedger(lambda group, text: saved.__setitem__(group, text))
    ledger.begin_generation()
    group = ledger.group
    for epoch, text in (("a", "第一句。"), ("b", "第二句。")):
        ledger.generating(epoch)
        turn = ledger.start(epoch)
        turn.samples, turn.text, turn.boundary = 240, [text], True
    ack = lambda epoch: ledger.acknowledge({"epoch": epoch, "consumed_samples": 240, "sample_rate": 24000, "completed": True})
    assert ack("b") and not saved
    assert ack("a") and saved[group] == "第一句。第二句。"
    ledger.begin_generation()
    ledger.generating("c")
    turn = ledger.start("c")
    turn.samples, turn.text, turn.boundary = 240, ["新回复。"], True
    assert ack("c") and len(saved) == 2
    assert not ack("a")


def test_failure_and_interruption_prevent_unplayed_prefix():
    saved = {}
    ledger = PlaybackLedger(lambda group, text: saved.__setitem__(group, text))
    for epoch, text in (("a", "已听。"), ("b", "失败。"), ("c", "后续。")):
        ledger.generating(epoch)
        turn = ledger.start(epoch)
        turn.samples, turn.text, turn.boundary = 10, [text], True
    ack = lambda epoch: ledger.acknowledge({"epoch": epoch, "consumed_samples": 10, "sample_rate": 24000, "completed": True})
    assert ack("a")
    ledger.fail_generation("b")
    assert ack("c") and not ack("b")
    assert list(saved.values()) == ["已听。"]
    ledger.interrupt()
    assert not ack("b")


def test_late_ack_updates_reserved_response_in_original_order(tmp_path):
    from server.storage import Store
    store = Store(tmp_path)
    session = store.session()
    ids = {}
    def begin(group):
        ids[group] = store.add_message(session, "assistant", "")
    ledger = PlaybackLedger(lambda group, text: store.update_message(ids[group], session, text), on_begin=begin)
    store.add_message(session, "user", "首问")
    ledger.begin_generation()
    ledger.generating("old")
    turn = ledger.start("old")
    turn.samples, turn.text, turn.boundary = 10, ["旧答。"], True
    store.add_message(session, "user", "新问")
    ledger.begin_generation()
    ledger.generating("new")
    turn = ledger.start("new")
    turn.samples, turn.text, turn.boundary = 10, ["新答。"], True
    ack = lambda epoch: ledger.acknowledge({"epoch": epoch, "consumed_samples": 10, "sample_rate": 24000, "completed": True})
    assert ack("new") and ack("old")
    assert [message["content"] for message in store.messages(session)] == ["首问", "旧答。", "新问", "新答。"]


def test_more_than_200_completed_groups_do_not_exhaust_window():
    saved = {}
    ledger = PlaybackLedger(lambda group, text: saved.__setitem__(group, text))
    for index in range(220):
        ledger.begin_generation()
        epoch = str(index)
        ledger.generating(epoch)
        turn = ledger.start(epoch)
        turn.samples, turn.text, turn.boundary = 10, [f"句{index}"], True
        assert ledger.acknowledge({"epoch": epoch, "consumed_samples": 10, "sample_rate": 24000, "completed": True})
    assert len(ledger.turns) <= 2
    assert len(ledger.epoch_groups) <= 2
    assert len(ledger.group_prefix) <= 128


def test_more_than_200_confirmed_sentences_in_one_group_do_not_exhaust_window():
    saved = {}
    ledger = PlaybackLedger(lambda group, text: saved.__setitem__(group, text))
    ledger.begin_generation()
    for index in range(220):
        epoch = str(index)
        ledger.generating(epoch)
        turn = ledger.start(epoch)
        turn.samples, turn.text, turn.boundary = 10, ["句"], True
        assert ledger.acknowledge({"epoch": epoch, "consumed_samples": 10, "sample_rate": 24000, "completed": True})
    assert list(saved.values()) == ["句" * 220]
    assert len(ledger.turns) == 0 and len(ledger.epoch_groups) == 0


def test_more_than_200_interrupted_groups_do_not_accumulate_empty_prefixes():
    ledger = PlaybackLedger(lambda _group, _text: None)
    for index in range(220):
        ledger.begin_generation()
        ledger.generating(str(index))
        turn = ledger.start(str(index))
        turn.samples, turn.text, turn.boundary = 10, ["未播放"], True
        ledger.interrupt()
    ledger.begin_generation()
    ledger.generating("good")
    turn = ledger.start("good")
    turn.samples, turn.text, turn.boundary = 10, ["正常"], True
    assert ledger.acknowledge({"epoch": "good", "consumed_samples": 10, "sample_rate": 24000, "completed": True})
    assert ledger.confirmed_text == ["正常"]
    assert len(ledger.turns) <= 2 and len(ledger.group_prefix) <= 2


@pytest.mark.asyncio
async def test_reverse_ack_same_full_text_keeps_generation_prefix_order():
    ledger = PlaybackLedger(lambda _group, _text: None)
    for epoch, text in (("old", "同样"), ("new", "同样的回答")):
        ledger.begin_generation()
        ledger.generating(epoch)
        turn = ledger.start(epoch)
        turn.samples, turn.text, turn.boundary = 10, [text], True
    ack = lambda epoch: ledger.acknowledge({"epoch": epoch, "consumed_samples": 10, "sample_rate": 24000, "completed": True})
    assert ack("new") and ack("old")
    processor = ConfirmedContext(ledger, [])
    result = []
    async def capture(frame, _direction):
        result.extend(frame.context.messages)
    processor.push_frame = capture
    context = LLMContext(messages=[{"role": "assistant", "content": "同样的回答"}, {"role": "user", "content": "问"}, {"role": "assistant", "content": "同样的回答"}])
    await processor.process_frame(LLMContextFrame(context), FrameDirection.DOWNSTREAM)
    assert [m["content"] for m in result] == ["同样", "问", "同样的回答"]


@pytest.mark.asyncio
async def test_live_prompt_uses_existing_character_budget_and_bounded_shared_context():
    initial = [{"role": "system", "content": "设定"}]
    context = LLMContext(messages=[*initial, *[{"role": "user", "content": str(index) + "字" * 1000} for index in range(220)]])
    processor = ConfirmedContext(PlaybackLedger(lambda _group, _text: None), initial)
    result = []
    async def capture(frame, _direction):
        result.extend(frame.context.messages)
    processor.push_frame = capture
    await processor.process_frame(LLMContextFrame(context), FrameDirection.DOWNSTREAM)
    assert sum(len(m["content"]) for m in result) <= 20000
    assert result[0]["role"] == "system" and result[1]["role"] == "user"
    assert result[-1]["content"].startswith("219")
    assert len(context.messages) <= 161


@pytest.mark.asyncio
async def test_pending_sentence_text_is_bounded_and_cleared_on_interrupt():
    processor = PlaybackStart(PlaybackLedger(lambda _group, _text: None))
    output = []
    async def capture(frame, _direction=FrameDirection.DOWNSTREAM):
        output.append(frame)
    processor.push_frame = capture
    for index in range(130):
        frame = AggregatedTextFrame(f"句{index}", text_type="sentence")
        frame.context_id = str(index)
        frame.will_be_spoken = True
        await processor.process_frame(frame, FrameDirection.DOWNSTREAM)
    assert len(processor.pending_text) == 128
    async def no_task():
        pass
    processor._start_interruption = no_task
    await processor.process_frame(InterruptionFrame(), FrameDirection.DOWNSTREAM)
    assert not processor.pending_text
    await processor.process_frame(TTSStartedFrame(context_id="129"), FrameDirection.DOWNSTREAM)
    assert output[-2].message["data"]["text"] == ""






@pytest.mark.asyncio
async def test_streamed_token_text_is_committed_only_after_exact_ack():
    saved = []
    ledger = PlaybackLedger(lambda group, text: saved.append(text))
    ledger.begin_generation()
    events = []
    class RTVI:
        async def send_server_message(self, data):
            events.append(data)
    start = PlaybackStart(ledger)
    boundary = PlaybackBoundary(ledger, RTVI())
    async def forward(frame, direction=FrameDirection.DOWNSTREAM):
        await boundary.process_frame(frame, direction)
    async def discard(frame, direction=FrameDirection.DOWNSTREAM):
        pass
    start.push_frame = forward
    boundary.push_frame = discard
    await start.process_frame(TTSStartedFrame(context_id="token"), FrameDirection.DOWNSTREAM)
    for text in ("你好呀，", "我们", "慢慢聊。"):
        await start.process_frame(TTSTextFrame(text, text_type="token", context_id="token"), FrameDirection.DOWNSTREAM)
    frame = OutputAudioRawFrame(audio=b"\0\0" * 240, sample_rate=24000, num_channels=1)
    frame.context_id = "token"
    await start.process_frame(frame, FrameDirection.DOWNSTREAM)
    await start.process_frame(TTSStoppedFrame(context_id="token"), FrameDirection.DOWNSTREAM)
    assert events[-1]["text"] == "你好呀，我们慢慢聊。"
    assert not ledger.acknowledge({"epoch": "token", "consumed_samples": 239, "sample_rate": 24000, "completed": True})
    assert not saved
    assert ledger.acknowledge({"epoch": "token", "consumed_samples": 240, "sample_rate": 24000, "completed": True})
    assert saved == ["你好呀，我们慢慢聊。"]


@pytest.mark.asyncio
async def test_canonical_context_uses_confirmed_database_order_for_duplicate_responses(tmp_path):
    from server.storage import Store
    from server.context import context_messages
    store = Store(tmp_path)
    session = store.session()
    ids = {}
    ledger = PlaybackLedger(lambda group, text: store.update_message(ids[group], session, text),
                            on_begin=lambda group: ids.__setitem__(group, store.add_message(session, "assistant", "")),
                            on_retire=lambda group: store.delete_empty_assistant(ids[group], session) if group in ids else None)
    store.add_message(session, "user", "取消测试")
    ledger.begin_generation()
    ledger.generating("cancelled")
    ledger.interrupt()
    store.add_message(session, "user", "正式问候")
    ledger.begin_generation()
    ledger.generating("completed")
    turn = ledger.start("completed")
    turn.samples, turn.text, turn.boundary = 240, ["你好呀，我们慢慢聊。"], True
    assert ledger.acknowledge({"epoch": "completed", "consumed_samples": 240, "sample_rate": 24000, "completed": True})
    store.add_message(session, "user", "下一问")
    snapshot = lambda: context_messages(store.settings(private=True), store.memories(), store.messages(session))
    processor = ConfirmedContext(ledger, [], snapshot=snapshot)
    output = []
    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        output.append(frame)
    processor.push_frame = capture
    native = LLMContext(messages=[{"role": "system", "content": "old"}, {"role": "user", "content": "取消测试"}, {"role": "assistant", "content": "你好呀，我们慢慢聊。"}, {"role": "user", "content": "正式问候"}, {"role": "assistant", "content": "你好呀，我们慢慢聊。"}])
    await processor.process_frame(LLMContextFrame(native), FrameDirection.DOWNSTREAM)
    assert [(x["role"], x["content"]) for x in output[0].context.messages[1:]] == [("user", "取消测试"), ("user", "正式问候"), ("assistant", "你好呀，我们慢慢聊。"), ("user", "下一问")]
