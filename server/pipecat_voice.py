"""Pipecat voice pipeline for one local WebSocket session."""

from __future__ import annotations

from fastapi import WebSocket
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame, ErrorFrame, Frame, InterruptionFrame, LLMContextFrame, LLMFullResponseStartFrame, MetricsFrame, OutputTransportMessageUrgentFrame,
                                   TranscriptionFrame, UserBackchannelFrame, VADUserStartedSpeakingFrame,
                                   VADUserStoppedSpeakingFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi.frames import RTVISendTextFrame
from pipecat.processors.frameworks.rtvi.processor import RTVIProcessor
from pipecat.processors.frameworks.rtvi import models as RTVI
from pydantic import ValidationError
from pipecat.observers.base_observer import BaseObserver
from pipecat.metrics.metrics import ProcessingMetricsData, TTFBMetricsData
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.deepseek.llm import DeepSeekLLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from speech.pipecat_services import LocalSpeechSTT, LocalSpeechTTS
from speech.pipecat_turns import ChineseBackchannelFilter, ChineseTurnStartStrategy
from .context import context_messages
from .playback import ConfirmedContext, PlaybackBoundary, PlaybackLedger, PlaybackStart
from .storage import Store
from .tts_policy import resolve_tts_mode, gpu_model_name
from .voice_metrics import registry
from .conversation import ConversationInputGate
from .voice_serializer import VoiceProtobufSerializer


def create_tts(settings):
    mode = resolve_tts_mode(settings)
    if mode == "api":
        if settings.get("tts_api_provider", "deepseek") == "deepseek":
            from speech.deepseek_tts import DeepSeekSpeechTTS
            return DeepSeekSpeechTTS(base_url=settings["tts_api_base_url"], api_key=settings["tts_api_key"],
                                     voice=settings["tts_api_voice"], timeout=settings["tts_api_timeout"],
                                     filter_markdown=settings.get("tts_api_filter_markdown", True))
        from speech.api_tts import APISpeechTTS
        return APISpeechTTS(base_url=settings["tts_api_base_url"], api_key=settings["tts_api_key"],
                            model=settings["tts_api_model"], voice=settings["tts_api_voice"],
                            speed=settings["tts_api_speed"], timeout=settings["tts_api_timeout"])
    if mode == "auto":
        from speech.auto_tts import AutoSpeechTTS
        return AutoSpeechTTS(moss_base_url=settings.get("moss_tts_url", "http://127.0.0.1:8772"),
                             index_base_url=settings.get("index_tts_url", "http://127.0.0.1:8770"),
                             gpu_model_name=gpu_model_name(settings),
                             voice=settings["voice"])
    address = settings.get("index_tts_url", "http://127.0.0.1:8770") if mode == "gpu" else settings.get("moss_tts_url", "http://127.0.0.1:8772")
    return LocalSpeechTTS(base_url=address, voice="default" if mode == "gpu" else settings["voice"], sample_rate=24000,
                          timeout=185 if mode == "gpu" else 120,
                          expected_model=gpu_model_name(settings) if mode == "gpu" else None,
                          reuse_context_id_within_turn=False)



class PriorityRTVIProcessor(RTVIProcessor):
    async def _handle_transport_message(self, frame):
        raw = frame.message
        data = raw.get("data") if isinstance(raw, dict) else None
        kind = data.get("t") if isinstance(data, dict) else None
        if isinstance(raw, dict) and raw.get("label") == RTVI.MESSAGE_LABEL and raw.get("type") == "client-message" and kind in {"voice.stop", "voice.playback", "voice.playback.stopped", "voice.capture", "voice.screen", "voice.screen.frame", "voice.screen.snapshot"}:
            try:
                message = RTVI.Message.model_validate(raw)
                payload = RTVI.RawClientMessageData.model_validate(message.data)
                if set(data) != {"t", "d"} or not isinstance(payload.d, dict) or (kind == "voice.stop" and payload.d):
                    raise ValueError("invalid priority message")
                if kind == "voice.capture" and (set(payload.d) != {"active"} or type(payload.d["active"]) is not bool):
                    raise ValueError("invalid capture message")
                if kind == "voice.screen" and (set(payload.d) != {"active", "stream_id"} or type(payload.d.get("active")) is not bool or not isinstance(payload.d.get("stream_id"), str)):
                    raise ValueError("invalid screen message")
            except (ValidationError, ValueError):
                await self.send_error("Invalid priority client message")
                return
            await self._handle_client_message(message.id, payload)
            return
        await super()._handle_transport_message(frame)


class TextHistory(FrameProcessor):
    def __init__(self, store: Store, session_id: str):
        super().__init__()
        self.store, self.session_id = store, session_id

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, RTVISendTextFrame):
            self.store.add_message(self.session_id, "user", frame.text)
        await self.push_frame(frame, direction)


class MissingKeyGuard(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, LLMContextFrame):
            await self.push_error(error_msg="请先在设置中填写 DeepSeek API 密钥。")
            return
        await self.push_frame(frame, direction)


class DuckObserver(BaseObserver):
    def __init__(self, metrics, ledger=None, input_gate=None, initiative=None, screen=None):
        super().__init__(observe_every_push=False)
        self.speaking = False
        self.ducked = False
        self.rtvi = None
        self.metrics = metrics
        self.ledger = ledger
        self.input_gate = input_gate
        self.initiative = initiative
        self.screen = screen

    async def on_push_frame(self, data):
        frame = data.frame
        if self.input_gate is not None:
            self.input_gate.observe(frame)
        if self.initiative is not None:
            self.initiative.observe(frame)
        if self.screen is not None:
            failed_screen = isinstance(frame, ErrorFrame) and self.screen.screen_reply
            self.screen.observe(frame)
            if failed_screen:
                await self.screen.notify({"type": "voice.screen.status", "status": "unavailable",
                    "reason": "screen_reply_failed_check_dsh_image_model", "source": "dsh", "model": "dsh-default"})
        if isinstance(frame, LLMFullResponseStartFrame) and self.ledger:
            self.ledger.begin_generation(frame.metadata.get("generation_id") or frame.metadata.get("dsh_request_id"))
        elif isinstance(frame, ErrorFrame) and isinstance(frame.processor, LocalSpeechTTS) and self.ledger:
            self.ledger.fail_generation(frame.metadata.get("tts_context_id"))
        if isinstance(frame, MetricsFrame):
            for item in frame.data:
                stage = next((name for prefix, name in (("LocalSpeechSTT", "stt"), ("LocalSpeechTTS", "tts"), ("OpenAILLMService", "llm"), ("DeepSeekLLMService", "llm")) if item.processor.startswith(prefix)), None)
                kind = "ttfb" if isinstance(item, TTFBMetricsData) else "processing" if isinstance(item, ProcessingMetricsData) else None
                if stage and kind:
                    self.metrics.add(f"{stage}.{kind}", item.value)
        elif isinstance(frame, InterruptionFrame):
            self.metrics.increment("interruptions")
        elif isinstance(frame, OutputTransportMessageUrgentFrame) and isinstance(frame.message, dict):
            payload = frame.message.get("data", {})
            if isinstance(payload, dict) and payload.get("type") == "voice.speaker" and payload.get("accepted") is not True:
                self.metrics.increment("speaker_rejections")
        if isinstance(frame, BotStartedSpeakingFrame):
            self.speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.speaking = False
        if isinstance(frame, VADUserStartedSpeakingFrame) and self.speaking and not self.ducked:
            self.ducked = True
            await self.rtvi.send_server_message({"type": "voice.duck", "active": True})
        elif self.ducked and isinstance(frame, (VADUserStoppedSpeakingFrame, TranscriptionFrame, UserBackchannelFrame, BotStoppedSpeakingFrame)):
            self.ducked = False
            await self.rtvi.send_server_message({"type": "voice.duck", "active": False})


async def run_voice(websocket: WebSocket, store: Store, session_id: str):
    settings = store.settings(private=True)
    metrics = registry.start(session_id)
    decision = None
    decision_context = lambda: ()
    if settings.get("systemone_enabled"):
        from .systemone import SystemOneClient, recent_context
        from .systemone_pipeline import SystemOneInput, SystemOneAffect
        decision = SystemOneClient(settings, metrics=metrics)
        decision_context = lambda: recent_context(store, session_id)
    is_dsh = getattr(store, "is_dsh_projection", False)
    base_url, api_key = ("dsh://active", "") if is_dsh else (settings["llm_base_url"], settings["llm_api_key"])
    missing_key = not is_dsh and "deepseek.com" in base_url and not api_key
    transport = FastAPIWebsocketTransport(websocket, FastAPIWebsocketParams(
        serializer=VoiceProtobufSerializer(), audio_in_enabled=True, audio_out_enabled=True,
        audio_in_sample_rate=16000, audio_out_sample_rate=24000, audio_out_end_silence_secs=0,
    ))
    context = LLMContext(messages=context_messages(settings, store.memories(), store.messages(session_id)))
    aggregators = LLMContextAggregatorPair(context, user_params=LLMUserAggregatorParams(
        vad_analyzer=SileroVADAnalyzer(params=VADParams(min_volume=0.3)),
        user_turn_strategies=UserTurnStrategies(start=[ChineseTurnStartStrategy()]),
        empty_user_turn=None,
    ))
    user, assistant = aggregators
    initiative = None
    screen = None
    if is_dsh:
        from .dsh_llm import DSHLLMService
        async def native_notify(data):
            if screen and data.get('type') == 'voice.native.user' and screen.idle:
                screen.idle.activity()
                screen.invalidate()
            await worker.rtvi.send_server_message(data)
        llm = DSHLLMService(store, session_id, settings, lambda: bool(initiative and initiative.initiative_reply),
                            notify=native_notify)
    else:
        llm_class = DeepSeekLLMService if "deepseek.com" in base_url else OpenAILLMService
        llm = llm_class(api_key=api_key or "local", base_url=base_url,
                        settings=llm_class.Settings(model=settings["llm_model"], temperature=settings["temperature"]))
    stt = LocalSpeechSTT(base_url=settings["speech_base_url"], owner_only=settings["owner_voice_only"],
                         streaming_preview=settings["streaming_asr_preview"], decision_metadata=decision is not None,
                         decision_audio=decision is not None and settings.get("systemone_audio_enabled", True))
    tts = create_tts(settings)
    input_gate = ConversationInputGate(settings.get("conversation_mode", "duplex"))
    processors = [transport.input(), input_gate, stt]
    if is_dsh:
        from .screen_voice import ScreenVoice, ScreenReplyGate
        from .companion_context import native_context
        async def background_context():
            if not llm._ready.is_set():
                return None
            return await native_context(store.bridge, session_id)
        async def screen_status(data):
            await worker.rtvi.send_server_message(data)
        screen_settings = dict(settings)
        if not getattr(store, 'screen_model_ready', False):
            screen_settings['screen_companion_enabled'] = False
        screen = ScreenVoice(decision, screen_settings, decision_context, notify=screen_status,
                             native_context=background_context)
        processors.append(screen)
    initiative = None
    if decision:
        processors.append(SystemOneInput(decision, decision_context, owner_only=settings["owner_voice_only"]))
        if settings.get("systemone_initiative_enabled") and not missing_key:
            from .systemone_initiative import SystemOneInitiative, InitiativeReplyGate, InitiativeSpeechLimit
            initiative = SystemOneInitiative(decision, decision_context, stt.transcribe_snapshot, settings)
            processors.append(initiative)
    processors.extend([ChineseBackchannelFilter(), user, TextHistory(store, session_id)])
    if missing_key:
        processors.append(MissingKeyGuard())
    saved_groups = {}
    def begin_response(group):
        saved_groups[group] = store.add_message(session_id, "assistant", "")
    def retire_response(group):
        message_id = saved_groups.pop(group, None)
        if message_id:
            store.delete_empty_assistant(message_id, session_id)
    def save_confirmed(group, text):
        if is_dsh and llm.is_preview(group):
            store.enqueue_playback(group, text)
        if group in saved_groups:
            store.update_message(saved_groups[group], session_id, text)
        else:
            saved_groups[group] = store.add_message(session_id, "assistant", text)
    ledger = PlaybackLedger(save_confirmed, metrics, begin_response, retire_response)
    playback_boundary = PlaybackBoundary(ledger, None)
    def confirmed_snapshot():
        return context_messages(store.settings(private=True), store.memories(), store.messages(session_id))
    affect = [SystemOneAffect(decision, decision_context)] if decision else []
    reply_gate, speech_limit = [], []
    def playback_busy():
        return (any(not turn.confirmed and not turn.interrupted for turn in ledger.turns.values())
            or any(epoch not in ledger.turns and epoch not in ledger.failed_epochs for epoch in ledger.epoch_groups))
    if initiative:
        initiative.playback_busy = lambda: playback_busy() or bool(screen and (
            screen.pending_reply or screen.screen_reply or screen.control.task is not None
            or (screen.idle and screen.idle.pending)
            or initiative.clock() - screen.control.budget.last_reply < initiative.cooldown))
        limiter = InitiativeSpeechLimit(max_chars=initiative.max_reply_chars)
        reply_gate = [InitiativeReplyGate(initiative, confirmed_snapshot, limiter)]
        speech_limit = [limiter]
    if screen:
        screen.playback_busy = playback_busy
        screen.external_busy = lambda: bool(llm._active_requests or llm._generation or not llm._ready.is_set())
        if initiative:
            screen.is_initiative = lambda: bool(initiative.initiative_reply)
            # Avoid a recursive busy() dependency. One common last-spoke clock
            # prevents speech-driven and screen-driven interjections alternating.
            screen.external_busy = lambda: (bool(llm._active_requests or llm._generation) or not llm._ready.is_set()
                or bool(initiative.tasks) or initiative.pending_generation or initiative.initiative_reply
                or initiative.clock() - initiative.last_spoke < settings.get("screen_companion_cooldown_s", 30))
            screen.on_accept = lambda: setattr(initiative, "last_spoke", initiative.clock())
        reply_gate.append(ScreenReplyGate(screen, confirmed_snapshot))
    pipeline = Pipeline([*processors, ConfirmedContext(ledger, context.messages, snapshot=confirmed_snapshot), *reply_gate, llm, *speech_limit, tts, *affect,
                         PlaybackStart(ledger), transport.output(), playback_boundary, assistant])
    duck = DuckObserver(metrics, ledger, input_gate, initiative, screen)
    worker = PipelineWorker(pipeline, params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=24000,
                                                            enable_metrics=True, send_initial_empty_metrics=False),
                            idle_timeout_secs=None, conversation_id=session_id, observers=[duck],
                            rtvi_processor=PriorityRTVIProcessor())
    duck.rtvi = worker.rtvi
    playback_boundary.rtvi = worker.rtvi
    runner = WorkerRunner(handle_sigint=False, handle_sigterm=False)
    @worker.rtvi.event_handler("on_client_message")
    async def on_client_message(rtvi, message):
        if message.type == "voice.stop":
            if initiative:
                initiative.cancel_pending()
            if screen:
                screen.invalidate()
                if screen.idle:
                    screen.idle.activity()
            ledger.interrupt()
            await rtvi.interrupt_bot()
            await rtvi.send_server_response(message, {"stopped": True})
        elif message.type == "voice.playback":
            accepted = ledger.acknowledge(message.data)
            if accepted and screen and screen.idle:
                screen.idle.activity(invalidate=False)
                screen.control.budget.mark_reply(screen.idle.clock())
            if not accepted:
                metrics.increment("ack_rejected")
            await rtvi.send_server_response(message, {"accepted": accepted})
        elif message.type == "voice.capture":
            if is_dsh:
                try:
                    await llm.set_microphone(message.data["active"])
                except Exception:
                    await rtvi.send_error("DSH voice state unavailable")
            if initiative:
                await initiative.set_capture_active(message.data["active"])
            if screen:
                screen.invalidate()
            await rtvi.send_server_response(message, {"accepted": True})
        elif message.type == "voice.screen":
            if screen:
                cancel_reply = screen.screen_reply
                accepted = await screen.control.activate(message.data)
                if not accepted and message.data['active'] and not getattr(store, 'screen_model_ready', False):
                    await rtvi.send_server_message({"type": "voice.screen.status", "status": "unavailable",
                        "reason": "requires_image_capable_dsh_model", "source": "local", "model": "none"})
                if accepted:
                    screen.request.sharing_changed()
                    if screen.idle:
                        screen.idle.invalidate()
                if accepted and not message.data["active"]:
                    screen.pending_reply = False
                    if cancel_reply:
                        await rtvi.interrupt_bot()
            else:
                accepted = False
                await rtvi.send_server_message({"type": "voice.screen.status", "status": "unavailable",
                    "reason": "requires_image_capable_dsh_model" if is_dsh and decision else "requires_dsh_and_systemone", "source": "local", "model": "none"})
            await rtvi.send_server_response(message, {"accepted": accepted})
        elif message.type == "voice.screen.frame":
            accepted = await screen.control.offer(message.data) if screen else False
            await rtvi.send_server_response(message, {"accepted": accepted})
        elif message.type == "voice.screen.snapshot":
            accepted = await screen.request.answer(message.data) if screen else False
            await rtvi.send_server_response(message, {"accepted": accepted})

    from .screen_registry import providers
    await runner.add_workers(worker)

    @user.event_handler("on_user_turn_message_added")
    async def save_user(_aggregator, message):
        if message.content:
            store.add_message(session_id, "user", message.content)

    @user.event_handler("on_user_backchannel")
    async def report_backchannel(_aggregator, message):
        await worker.rtvi.send_server_message({"type": "voice.backchannel", "text": message.content})

    @transport.event_handler("on_client_disconnected")
    async def on_disconnect(_transport, _client):
        if screen:
            if screen.idle:
                await screen.idle.close()
            screen.invalidate()
            screen.request.cancel_tool('no_connection')
            if providers.get(session_id) is screen.request:
                providers.pop(session_id, None)
        await runner.cancel()

    if screen:
        providers[session_id] = screen.request
    try:
        if is_dsh:
            await llm.start_listening()
            if screen and screen.idle:
                screen.idle.start()
        await runner.run()
    finally:
        if screen and screen.idle:
            await screen.idle.close()
        if is_dsh:
            await llm.close_listening()
        if screen:
            if providers.get(session_id) is screen.request:
                providers.pop(session_id, None)
            await screen.request.close()
            await screen.control.close()
        if is_dsh:
            ledger.interrupt()
        for group in list(saved_groups):
            retire_response(group)
