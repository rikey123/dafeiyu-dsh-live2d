"""Screen observations join the existing speech pipeline, never a second harness.

No screenshot is written to Store. Only actual playback acknowledgements may
commit the resulting assistant text through the existing PlaybackLedger.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pipecat.frames.frames import (BotStartedSpeakingFrame, BotStoppedSpeakingFrame,
    CancelFrame, DataFrame, EndFrame, ErrorFrame, InterruptionFrame, LLMContextFrame,
    LLMFullResponseStartFrame, LLMFullResponseEndFrame, TranscriptionFrame,
    VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.processors.frameworks.rtvi.frames import RTVISendTextFrame

# A gateway-process budget, not per WebSocket: reconnecting or changing sessions
# does not reset hourly screen spending. Nothing is persisted as user memory.
_shared_budget = None


@dataclass
class ScreenRequestFrame(DataFrame):
    image: dict = field(repr=False)
    intent: str
    generation: int
    max_chars: int


@dataclass
class IdleRequestFrame(DataFrame):
    image: dict | None = field(repr=False)
    generation: int
    stream_id: str | None


class ScreenVoice(FrameProcessor):
    def __init__(self, client, settings, context, *, notify, native_context=None, **kwargs):
        super().__init__(**kwargs)
        from .screen_companion import ScreenCompanion, ScreenBudget
        global _shared_budget
        if _shared_budget is None:
            _shared_budget = ScreenBudget()
        self.notify = notify
        self.user_speaking = self.bot_speaking = self.generating = False
        self.pending_reply = self.screen_reply = False
        self.playback_busy = lambda: False
        self.external_busy = lambda: False
        self.is_initiative = lambda: False
        self.on_accept = lambda: None
        if client is None:
            from types import SimpleNamespace
            client = SimpleNamespace(source='local', model='none', metrics=None)
        self.control = ScreenCompanion(client, settings, context=context,
            busy=self.busy, on_reply=self.offer_reply, on_status=notify, on_sample=notify, budget=_shared_budget,
            native_context=native_context)
        from .screen_request import RequestedScreen
        self.request = RequestedScreen(client, settings, self.control, context, notify)
        self.idle = None
        if native_context is not None:
            from .idle_companion import IdleCompanion
            self.idle = IdleCompanion(settings, self, native_context, notify=notify)
        self.control.log_status({'status': 'inactive', 'reason': 'awaiting_authorization'})

    def busy(self, *, ignore_pending=False):
        return (self.user_speaking or self.bot_speaking or self.generating
            or self.request.busy or self.request.tool_pending is not None
            or bool(self.idle and self.idle.pending) or (self.pending_reply and not ignore_pending) or self.playback_busy() or self.external_busy())

    def invalidate(self):
        self.control.cancel_pending()
        self.request.invalidate()
        if self.idle:
            self.idle.invalidate()
        self.pending_reply = False

    def observe(self, frame):
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self.user_speaking = True
            if self.idle:
                self.idle.activity()
            self.invalidate()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self.user_speaking = False
        elif isinstance(frame, (TranscriptionFrame, RTVISendTextFrame)):
            if self.idle and getattr(frame, "text", "").strip():
                self.idle.activity()
            self.invalidate()
        elif isinstance(frame, LLMFullResponseStartFrame):
            if frame.metadata.get("kind") not in {"screen", "idle"}:
                # Native asynchronous deliveries can start without a new local
                # user frame. They take priority over optional companionship;
                # invalidate only the preview, never the native DSH task.
                self.invalidate()
                if self.idle:
                    self.idle.activity()
            self.generating, self.pending_reply = True, False
            self.screen_reply = frame.metadata.get("kind") == "screen"
        elif isinstance(frame, LLMFullResponseEndFrame):
            self.generating = False
        elif isinstance(frame, BotStartedSpeakingFrame):
            self.bot_speaking = True
        elif isinstance(frame, BotStoppedSpeakingFrame):
            self.bot_speaking = self.screen_reply = False
        elif isinstance(frame, (InterruptionFrame, CancelFrame, EndFrame)):
            self.invalidate()
            self.generating = self.pending_reply = self.screen_reply = False
            if isinstance(frame, (CancelFrame, EndFrame)):
                self.user_speaking = self.bot_speaking = False
        elif isinstance(frame, ErrorFrame):
            self.invalidate()
            self.screen_reply = False

    async def offer_reply(self, image, intent, generation, max_chars):
        if not self.control.valid(generation) or self.busy():
            return False
        self.pending_reply = True
        await self.push_frame(ScreenRequestFrame(image, intent, generation, max_chars))
        return True

    async def offer_idle(self, image, generation, stream_id):
        if not self.idle or not self.idle.valid(generation, stream_id):
            return False
        self.pending_reply = True
        await self.push_frame(IdleRequestFrame(image, generation, stream_id))
        return True

    async def cleanup(self):
        if self.idle:
            await self.idle.close()
        self.invalidate()
        await self.request.close()
        await self.control.close()
        await super().cleanup()

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)


class ScreenReplyGate(FrameProcessor):
    """After ConfirmedContext; no fake user turn or image in the shared context."""
    def __init__(self, screen, snapshot, **kwargs):
        super().__init__(**kwargs)
        self.screen, self.snapshot = screen, snapshot

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        screen = self.screen
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, IdleRequestFrame):
            idle = screen.idle
            if (not idle or not screen.pending_reply or not idle.valid(frame.generation, frame.stream_id)
                    or idle.busy(ignore_pending=True)):
                screen.pending_reply = False
                return
            screen.on_accept()
            prompt = "已经安静了一段时间。请结合当前情境和你的兴趣自然地聊一句，不要催促或施压；如果不适合说话，可以保持安静。"
            if frame.image is not None:
                prompt += "若想聊附带的新画面，直接分享自己的看法、感受或吐槽，细节只用来点明话头，不要先概述画面。"
            context = LLMContext(messages=[*self.snapshot(), {"role": "user", "content": prompt}])
            request = LLMContextFrame(context)
            request.metadata["dafeiyu_idle"] = {"image": frame.image,
                "max_reply_chars": screen.control.settings.get("idle_companion_max_reply_chars", 64)}
            request.metadata["dafeiyu_idle_valid"] = lambda: idle.valid(frame.generation, frame.stream_id) and not screen.user_speaking
            request.metadata["dafeiyu_idle_current"] = lambda: idle.current(frame.generation, frame.stream_id) and not screen.user_speaking
            request.metadata["dafeiyu_idle_rejected"] = lambda: setattr(screen, "pending_reply", False)
            request.metadata["dafeiyu_preview_finished"] = lambda: setattr(screen, "pending_reply", False)
            await self.push_frame(request, direction)
            return
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, ScreenRequestFrame):
            if not screen.pending_reply or not screen.control.valid(frame.generation) or screen.busy(ignore_pending=True):
                screen.pending_reply = False
                return
            screen.on_accept()
            screen.screen_reply = True
            prompt = ("这是你主动陪用户一起看屏幕时想说的一句，不是用户要求描述画面。"
                      "直接聊你对具体细节的看法、感受、吐槽或联想，细节只用来点明话头，不要先概述画面。"
                      "结合你的人设和近期交流，有趣时自然抖个机灵，不必硬逗，也不必每次反问。"
                      f"尽量约{frame.max_chars}字，保持句子完整。")
            if frame.intent == "direct":
                prompt += "自行决定此刻有没有想分享的内容，不必每帧说话；没有值得补充的内容或不适合时可以保持安静。"
            context = LLMContext(messages=[*self.snapshot(), {"role": "user", "content": prompt}])
            request = LLMContextFrame(context)
            request.metadata["dafeiyu_screen"] = {"image": frame.image, "max_reply_chars": frame.max_chars,
                "screen_mode": screen.control.settings.get("screen_companion_mode", "systemone")}
            request.metadata["dafeiyu_screen_valid"] = lambda: screen.control.valid(frame.generation) and not screen.user_speaking
            request.metadata["dafeiyu_screen_current"] = lambda: screen.control.current(frame.generation) and not screen.user_speaking
            def rejected():
                screen.pending_reply = screen.screen_reply = False
            request.metadata["dafeiyu_screen_rejected"] = rejected
            request.metadata["dafeiyu_preview_finished"] = rejected
            if not request.metadata["dafeiyu_screen_valid"]():
                screen.pending_reply = screen.screen_reply = False
                return
            await self.push_frame(request, direction)
            return
        if direction == FrameDirection.DOWNSTREAM and isinstance(frame, LLMContextFrame):
            screen.invalidate()
            screen.screen_reply = False
            # Initiative fragments are not completed user requests. They must
            # not cause screen capture or a second semantic classification.
            if not screen.is_initiative() and not await screen.request.prepare(frame):
                return
        await self.push_frame(frame, direction)
