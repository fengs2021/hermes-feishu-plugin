"""Feishu CardKit-first streaming transport aligned with OpenClaw."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

from ..channel.runtime_state import (
    advance_card_sequence,
    disable_cardkit_streaming,
    get_card_id,
    get_chat_state,
    get_display_text,
    get_generation,
    get_original_card_id,
    get_pending_status_text,
    get_thinking_elapsed_ms,
    get_thinking_text,
    get_tool_elapsed_ms,
    remember_card_entity,
    remember_card_message,
    remember_display_text,
    remember_last_flushed_text,
    remember_thinking_text,
    remember_tool_steps,
)
from ..channel.state import get_chat_generation, get_reply_to_message_id
from ..channel.status_filter import parse_tool_progress_lines, should_suppress_status_message
from ..core.i18n import select_text
from ..core.mode import should_stream
from .builder import (
    STREAMING_ELEMENT_ID,
    build_complete_card,
    build_streaming_patch_card,
    build_streaming_pre_answer_card,
    split_reasoning_text,
    to_cardkit2,
)
from .cardkit import (
    create_card_entity,
    extract_message_id,
    patch_interactive_card,
    send_card_reference,
    send_interactive_card,
    set_card_streaming_mode,
    stream_card_content,
    update_card,
)
from .errors import is_card_rate_limit_error, is_card_table_limit_error
from .flush_controller import FlushController
from .live_state import current_heartbeat_text, current_progress_text, elapsed_ms, get_card_update_lock, should_show_tool_use, visible_tool_steps
from .streaming_support import clear_heartbeat_task, ensure_progress_heartbeat, get_heartbeat_task, is_feishu_adapter, resolve_reply_to_message_id, response_ok, strip_cursor
from .tool_panels import (
    build_streaming_thinking_active_panel,
    build_streaming_thinking_pending_panel,
    THINKING_ELEMENT_ID,
)

logger = logging.getLogger(__name__)

CARDKIT_UPDATE_INTERVAL_SECONDS = 0.1
PATCH_UPDATE_INTERVAL_SECONDS = 1.5
TOOL_STATUS_UPDATE_INTERVAL_SECONDS = 1.5
THINKING_THROTTLE_SECONDS = 0.3


def _resolve_expected_generation(adapter: Any, chat_id: str, owner: Any | None = None) -> int:
    if owner is not None:
        cached = int(getattr(owner, "_hermes_feishu_generation", 0) or 0)
        if cached > 0:
            return cached
    expected = int(get_chat_generation() or 0)
    if expected <= 0:
        expected = int(get_generation(adapter, chat_id) or 0)
    if owner is not None:
        setattr(owner, "_hermes_feishu_generation", expected)
    return expected


def _generation_matches(adapter: Any, chat_id: str, expected_generation: int) -> bool:
    if expected_generation <= 0:
        return True
    return expected_generation == get_generation(adapter, chat_id)


async def _ensure_card_created(
    adapter: Any,
    chat_id: str,
    *,
    reply_to: str | None,
    metadata: Any = None,
    expected_generation: int = 0,
) -> str | None:
    """Create the single reply card via CardKit, falling back to IM card."""

    if expected_generation <= 0:
        expected_generation = _resolve_expected_generation(adapter, chat_id)
    if not _generation_matches(adapter, chat_id, expected_generation):
        return None
    state = get_chat_state(adapter, chat_id)
    if state.card_message_id:
        return state.card_message_id
    # Note: reply_to may be None for DM (no parent message to reply to).
    # send_card_reference handles None by creating a new message instead of replying.
    if state.card_create_lock is None:
        state.card_create_lock = asyncio.Lock()

    async with state.card_create_lock:
        if state.card_message_id:
            logger.info("[Feishu Streaming] _ensure_card_created SKIP: already have card_id=%s", state.card_message_id)
            return state.card_message_id

        steps = visible_tool_steps(adapter, chat_id)
        tool_elapsed_ms = get_tool_elapsed_ms(adapter, chat_id)
        status_text = get_pending_status_text(adapter, chat_id)
        initial_card = build_streaming_pre_answer_card(
            tool_steps=steps,
            tool_elapsed_ms=tool_elapsed_ms,
            status_text=status_text,
            heartbeat_text=current_heartbeat_text(adapter, chat_id),
            show_tool_use=should_show_tool_use(adapter, chat_id),
            thinking_text=get_thinking_text(adapter, chat_id),
            thinking_elapsed_ms=get_thinking_elapsed_ms(adapter),
        )

        try:
            card_id = await create_card_entity(adapter, initial_card)
            remember_card_entity(adapter, chat_id, card_id)
            logger.info("[Feishu Streaming] CardKit card created card_id=%s, sending reference to chat=%s", card_id, chat_id)
            response = await send_card_reference(
                adapter,
                chat_id=chat_id,
                card_id=card_id,
                reply_to=reply_to,
                metadata=metadata,
            )
            if not response_ok(response):
                raise RuntimeError(f"send CardKit reference failed: code={getattr(response, 'code', None)} msg={getattr(response, 'msg', None)}")
            message_id = extract_message_id(response)
            if not message_id:
                raise RuntimeError("send CardKit reference succeeded but no message_id was returned")
            remember_card_message(adapter, chat_id, message_id)
            logger.info("[Feishu Streaming] CardKit card REGISTERED: msg_id=%s chat=%s", message_id, chat_id)
            state.phase = "streaming"
            state.flush_controller = FlushController(
                lambda: _perform_answer_flush(adapter, chat_id, expected_generation=expected_generation)
            )
            state.flush_controller.set_ready(True)
            await ensure_progress_heartbeat(
                adapter,
                chat_id,
                lambda inner_adapter, inner_chat_id: sync_progress_card(
                    inner_adapter,
                    inner_chat_id,
                    expected_generation=expected_generation,
                ),
            )
            return message_id
        except Exception as exc:
            logger.warning("hermes_feishu_plugin CardKit flow failed; falling back to IM card: %s", exc)
            disable_cardkit_streaming(adapter, chat_id)
            if not state.card_message_id:
                state.original_card_id = ""
                state.card_sequence = 0

            fallback_card = build_streaming_patch_card(
                tool_steps=steps,
                status_text=status_text,
                show_tool_use=should_show_tool_use(adapter, chat_id),
                thinking_text=get_thinking_text(adapter, chat_id),
                thinking_elapsed_ms=get_thinking_elapsed_ms(adapter),
            )
            # Guard: another coroutine may have succeeded via CardKit while we were
            # falling back.  Avoid overwriting the message_id that is already stored.
            if state.card_message_id:
                return state.card_message_id

            response = await send_interactive_card(
                adapter,
                chat_id=chat_id,
                card=fallback_card,
                reply_to=reply_to,
                metadata=metadata,
            )
            if not response_ok(response):
                logger.warning(
                    "hermes_feishu_plugin fallback IM card send failed: code=%s msg=%s",
                    getattr(response, "code", None),
                    getattr(response, "msg", None),
                )
                return None
        message_id = extract_message_id(response)
        if message_id:
            # Double-check again — another CardKit attempt may have completed
            # during the IM send.  Prefer the CardKit message when available.
            if state.card_message_id:
                return state.card_message_id
            remember_card_message(adapter, chat_id, message_id)
            state.phase = "streaming"
            state.flush_controller = FlushController(
                lambda: _perform_answer_flush(adapter, chat_id, expected_generation=expected_generation)
            )
            state.flush_controller.set_ready(True)
            await ensure_progress_heartbeat(
                adapter,
                chat_id,
                lambda inner_adapter, inner_chat_id: sync_progress_card(
                    inner_adapter,
                    inner_chat_id,
                    expected_generation=expected_generation,
                ),
            )
        return message_id


async def _perform_answer_flush(adapter: Any, chat_id: str, *, expected_generation: int = 0) -> None:
    """Flush accumulated answer text via CardKit or IM patch fallback."""
    if not _generation_matches(adapter, chat_id, expected_generation):
        return
    state = get_chat_state(adapter, chat_id)
    message_id = state.card_message_id
    if not message_id or state.phase in {"completed", "aborted", "terminated"}:
        return

    text = state.display_text
    if text == state.last_flushed_text:
        return

    active_card_id = get_card_id(adapter, chat_id)
    if active_card_id:
        try:
            async with get_card_update_lock(adapter, chat_id):
                sequence = advance_card_sequence(adapter, chat_id)
                await stream_card_content(
                    adapter,
                    card_id=active_card_id,
                    element_id=STREAMING_ELEMENT_ID,
                    content=text,
                    sequence=sequence,
                )
                remember_last_flushed_text(adapter, chat_id, text)
                return
        except Exception as exc:
            if is_card_rate_limit_error(exc):
                logger.info("hermes_feishu_plugin CardKit rate limited; skipping frame")
                return
            if is_card_table_limit_error(exc):
                logger.warning("hermes_feishu_plugin CardKit table limit hit; disabling intermediate CardKit streaming")
                disable_cardkit_streaming(adapter, chat_id)
                return
            logger.warning("hermes_feishu_plugin CardKit stream failed; disabling CardKit streaming: %s", exc)
            disable_cardkit_streaming(adapter, chat_id)

    if get_original_card_id(adapter, chat_id):
        return

    card = build_streaming_patch_card(
        text=text,
        tool_steps=visible_tool_steps(adapter, chat_id),
        status_text=get_pending_status_text(adapter, chat_id),
        heartbeat_text=current_heartbeat_text(adapter, chat_id),
        show_tool_use=should_show_tool_use(adapter, chat_id),
        thinking_text=get_thinking_text(adapter, chat_id),
        thinking_elapsed_ms=get_thinking_elapsed_ms(adapter),
    )
    async with get_card_update_lock(adapter, chat_id):
        response = await patch_interactive_card(adapter, message_id=message_id, card=card)
    if response_ok(response):
        remember_last_flushed_text(adapter, chat_id, text)


async def _flush_answer(adapter: Any, chat_id: str, *, expected_generation: int = 0) -> None:
    if not _generation_matches(adapter, chat_id, expected_generation):
        return
    state = get_chat_state(adapter, chat_id)
    if not state.flush_controller:
        state.flush_controller = FlushController(
            lambda: _perform_answer_flush(adapter, chat_id, expected_generation=expected_generation)
        )
        state.flush_controller.set_ready(bool(state.card_message_id))
    throttle = CARDKIT_UPDATE_INTERVAL_SECONDS if get_card_id(adapter, chat_id) else PATCH_UPDATE_INTERVAL_SECONDS
    await state.flush_controller.throttled_update(throttle)


async def sync_progress_card(
    adapter: Any,
    chat_id: str,
    metadata: Any = None,
    *,
    expected_generation: int = 0,
) -> str | None:
    """Create or update the single Feishu reply card for tool-progress updates."""
    if not should_stream(adapter, chat_id):
        return None
    if expected_generation <= 0:
        expected_generation = _resolve_expected_generation(adapter, chat_id)
    if not _generation_matches(adapter, chat_id, expected_generation):
        return None

    state = get_chat_state(adapter, chat_id)
    logger.info("[Feishu Streaming] _ensure_card_created called: chat=%s gen=%d existing_card=%s phase=%s",
                chat_id, expected_generation, state.card_message_id, state.phase)
    if state.phase in {"completed", "aborted", "terminated"}:
        return None
    reply_to = state.reply_to_message_id or get_reply_to_message_id().strip()
    message_id = await _ensure_card_created(
        adapter,
        chat_id,
        reply_to=reply_to,
        metadata=metadata,
        expected_generation=expected_generation,
    )
    if not message_id:
        return None

    steps = visible_tool_steps(adapter, chat_id)
    status_text = get_pending_status_text(adapter, chat_id)
    heartbeat_text = current_heartbeat_text(adapter, chat_id)
    text = current_progress_text(adapter, chat_id)
    if not steps and not status_text and not heartbeat_text:
        return message_id

    now = asyncio.get_running_loop().time()
    if state.last_tool_status_update_at and (now - state.last_tool_status_update_at) < TOOL_STATUS_UPDATE_INTERVAL_SECONDS:
        return message_id
    state.last_tool_status_update_at = now

    card = build_streaming_pre_answer_card(
        text=text,
        tool_steps=steps,
        tool_elapsed_ms=get_tool_elapsed_ms(adapter, chat_id),
        status_text=status_text,
        heartbeat_text=heartbeat_text,
        show_tool_use=should_show_tool_use(adapter, chat_id),
    )
    active_card_id = get_card_id(adapter, chat_id)
    if active_card_id:
        try:
            async with get_card_update_lock(adapter, chat_id):
                sequence = advance_card_sequence(adapter, chat_id)
                await update_card(adapter, card_id=active_card_id, card=card, sequence=sequence)
            return message_id
        except Exception as exc:
            if is_card_rate_limit_error(exc):
                return message_id
            logger.warning("hermes_feishu_plugin progress CardKit update failed: %s", exc)
            disable_cardkit_streaming(adapter, chat_id)
            return message_id

    if not get_original_card_id(adapter, chat_id):
        async with get_card_update_lock(adapter, chat_id):
            await patch_interactive_card(adapter, message_id=message_id, card=card)
    return message_id


async def _finalize_card(adapter: Any, chat_id: str, text: str, *, expected_generation: int = 0, close_card: bool = False) -> bool:
    if expected_generation <= 0:
        expected_generation = _resolve_expected_generation(adapter, chat_id)
    if not _generation_matches(adapter, chat_id, expected_generation):
        return False
    state = get_chat_state(adapter, chat_id)
    if state.phase == "completed":
        return True


    message_id = state.card_message_id
    if not message_id:
        return False

    state.phase = "completed"
    if state.flush_controller:
        state.flush_controller.complete()
        await state.flush_controller.wait_for_flush()
    # Stop the progress heartbeat so it doesn't overwrite the completed card
    # with streaming-in-progress content after this turn finishes.
    hb_task = get_heartbeat_task(adapter, chat_id)
    if hb_task and not hb_task.done():
        hb_task.cancel()
        clear_heartbeat_task(adapter, chat_id)

    thinking_for_card = get_thinking_text(adapter, chat_id)
    complete_card = build_complete_card(
        text=text,
        tool_steps=visible_tool_steps(adapter, chat_id),
        tool_elapsed_ms=get_tool_elapsed_ms(adapter, chat_id),
        elapsed_ms=elapsed_ms(adapter, chat_id),
        show_tool_use=should_show_tool_use(adapter, chat_id),
        thinking_text=thinking_for_card,
    )
    effective_card_id = get_card_id(adapter, chat_id) or get_original_card_id(adapter, chat_id)
    if effective_card_id:
        try:
            async with get_card_update_lock(adapter, chat_id):
                sequence = advance_card_sequence(adapter, chat_id)
                await set_card_streaming_mode(
                    adapter,
                    card_id=effective_card_id,
                    streaming_mode=False,
                    sequence=sequence,
                )
                sequence = advance_card_sequence(adapter, chat_id)
                await update_card(adapter, card_id=effective_card_id, card=to_cardkit2(complete_card), sequence=sequence)
            remember_display_text(adapter, chat_id, text)
            remember_last_flushed_text(adapter, chat_id, text)
            return True
        except Exception as exc:
            logger.warning("hermes_feishu_plugin final CardKit update failed; trying IM patch fallback: %s", exc)

    async with get_card_update_lock(adapter, chat_id):
        response = await patch_interactive_card(adapter, message_id=message_id, card=complete_card)
    if response_ok(response):
        remember_display_text(adapter, chat_id, text)
        remember_last_flushed_text(adapter, chat_id, text)
        return True
    return False


async def abort_progress_card(adapter: Any, chat_id: str, reason: str | None = None) -> bool:
    """Close an active progress card when a newer inbound turn supersedes it."""
    state = get_chat_state(adapter, chat_id)
    if not state.card_message_id or state.phase in {"completed", "aborted", "terminated"}:
        return False

    state.phase = "aborted"
    if state.flush_controller:
        state.flush_controller.complete()
        await state.flush_controller.wait_for_flush()

    text = str(reason or "").strip() or select_text(
        "已收到新消息，上一轮处理已停止，正在处理最新输入。",
        "New message received. The previous turn was stopped, and the latest input is being handled.",
    )
    thinking_for_abort = get_thinking_text(adapter, chat_id)
    aborted_card = build_complete_card(
        text=text,
        tool_steps=visible_tool_steps(adapter, chat_id),
        tool_elapsed_ms=get_tool_elapsed_ms(adapter, chat_id),
        elapsed_ms=elapsed_ms(adapter, chat_id),
        is_aborted=True,
        show_tool_use=should_show_tool_use(adapter, chat_id),
        thinking_text=thinking_for_abort,
    )
    effective_card_id = get_card_id(adapter, chat_id) or get_original_card_id(adapter, chat_id)
    if effective_card_id:
        try:
            async with get_card_update_lock(adapter, chat_id):
                sequence = advance_card_sequence(adapter, chat_id)
                await set_card_streaming_mode(
                    adapter,
                    card_id=effective_card_id,
                    streaming_mode=False,
                    sequence=sequence,
                )
                sequence = advance_card_sequence(adapter, chat_id)
                await update_card(adapter, card_id=effective_card_id, card=to_cardkit2(aborted_card), sequence=sequence)
            remember_display_text(adapter, chat_id, text)
            remember_last_flushed_text(adapter, chat_id, text)
            return True
        except Exception as exc:
            logger.warning("hermes_feishu_plugin abort CardKit update failed; trying IM patch fallback: %s", exc)

    async with get_card_update_lock(adapter, chat_id):
        response = await patch_interactive_card(adapter, message_id=state.card_message_id, card=aborted_card)
    if response_ok(response):
        remember_display_text(adapter, chat_id, text)
        remember_last_flushed_text(adapter, chat_id, text)
        return True
    return False


async def sync_thinking_card(
    adapter: Any,
    chat_id: str,
    *,
    expected_generation: int = 0,
) -> None:
    """Sync thinking panel in the active card (throttled)."""
    if expected_generation <= 0:
        expected_generation = _resolve_expected_generation(adapter, chat_id)
    if not _generation_matches(adapter, chat_id, expected_generation):
        return
    state = get_chat_state(adapter, chat_id)
    if not state.card_message_id or state.phase in {"completed", "aborted", "terminated"}:
        return

    thinking_text = get_thinking_text(adapter, chat_id)
    if not thinking_text:
        return

    now = asyncio.get_running_loop().time()
    last = getattr(state, "last_thinking_update_at", 0.0) or 0.0
    if last > 0 and (now - last) < THINKING_THROTTLE_SECONDS:
        return
    state.last_thinking_update_at = now

    active_card_id = get_card_id(adapter, chat_id)
    if active_card_id:
        try:
            # Stream thinking content into the thinking_text element for typewriter effect
            display_text = thinking_text[-3000:] if len(thinking_text) > 3000 else thinking_text
            async with get_card_update_lock(adapter, chat_id):
                sequence = advance_card_sequence(adapter, chat_id)
                await stream_card_content(
                    adapter,
                    card_id=active_card_id,
                    element_id="thinking_text",
                    content=display_text,
                    sequence=sequence,
                )
            return
        except Exception as exc:
            if is_card_rate_limit_error(exc):
                return
            logger.warning("hermes_feishu_plugin thinking CardKit update failed: %s", exc)
            disable_cardkit_streaming(adapter, chat_id)

    # IM patch fallback
    if not get_original_card_id(adapter, chat_id):
        return
    try:
        thinking_elapsed = get_thinking_elapsed_ms(adapter)
        panel = build_streaming_thinking_active_panel(
            thinking_text,
            elapsed_ms=thinking_elapsed,
        )
        async with get_card_update_lock(adapter, chat_id):
            response = await patch_interactive_card(
                adapter,
                message_id=state.card_message_id,
                card={"config": {"update_multi": True}, "elements": [panel]},
            )
    except Exception as exc:
        logger.warning("hermes_feishu_plugin thinking IM patch failed: %s", exc)


_thread_consumer_map: dict[int, Any] = {}
"""Map from thread identity to the Feishu stream consumer for that thread.

Set by ``wrapped_send_or_edit`` when the LLM call starts (async thread),
read by ``_handle_reasoning_delta`` when the worker thread fires reasoning
deltas.  Each thread has its own dict slot so concurrent LLM calls don't
overwrite each other.
"""

_reasoning_delta_lock = threading.Lock()
# Global map: AIAgent id(self) -> GatewayStreamConsumer
_agent_consumer_map: dict[int, Any] = {}

# Pending reasoning buffer: when MiniMax reasoning_content arrives before the
# GatewayStreamConsumer has registered itself in _agent_consumer_map (i.e. before
# the first text delta), we buffer the content here keyed by thread_ident.
# When the consumer finally registers (same thread), wrapped_send_or_edit drains
# this buffer and uses it to seed the thinking panel.
# Using thread_ident (not agent_id) because gateway may create different
# AIAgent instances for the reasoning stream vs the text stream.
_pending_reasoning_by_thread: dict[int, str] = {}


def _handle_reasoning_delta(reasoning_text: str, agent_id: int | None = None) -> None:
    """Thread-safe handler for reasoning deltas from the agent worker thread.

    Accumulates reasoning text and streams it into the CardKit thinking panel
    in real time via ``stream_card_content`` on the ``thinking_text`` element.
    When the card hasn't been created yet (reasoning arrives before the first
    text token), eagerly creates the card so the thinking panel can stream.
    Falls back to a full-card ``sync_thinking_card`` when CardKit streaming
    is unavailable (IM patch mode).

    agent_id is the id() of the AIAgent instance. When provided, we look up
    the consumer via the agent map. Falls back to the legacy thread-ident map
    for backward compatibility with non-hooked callers.
    """
    logger.info("[Feishu Streaming] _handle_reasoning_delta called: len=%d agent_id=%s",
                len(reasoning_text or ""), agent_id)
    consumer = None
    if agent_id is not None:
        consumer = _agent_consumer_map.get(agent_id)
        logger.info("[Feishu Streaming] _handle_reasoning_delta: agent_id=%s consumer=%s", agent_id, consumer)
    # Fallback: legacy thread-ident map
    if consumer is None:
        thread_key = threading.current_thread().ident
        consumer = _thread_consumer_map.get(thread_key)
        logger.info("[Feishu Streaming] _handle_reasoning_delta: thread_fallback key=%s consumer=%s", thread_key, consumer)
    # consumer is None means reasoning arrived before the first text delta
    # (MiniMax sends reasoning_content before any text token).
    # Buffer it per thread so wrapped_send_or_edit (same thread) can drain it.
    if consumer is None:
        thread_key = threading.current_thread().ident
        if reasoning_text:
            with _reasoning_delta_lock:
                _pending_reasoning_by_thread[thread_key] = (
                    _pending_reasoning_by_thread.get(thread_key, "") + reasoning_text
                )
            logger.info(
                "[Feishu Streaming] _handle_reasoning_delta: no consumer yet, "
                "buffered reasoning for thread=%s (total=%d)",
                thread_key,
                len(_pending_reasoning_by_thread.get(thread_key, "")),
            )
        return
    if not reasoning_text:
        return
    adapter = getattr(consumer, "adapter", None)
    chat_id = getattr(consumer, "chat_id", None)
    if not adapter or not chat_id or not is_feishu_adapter(adapter):
        logger.warning("[Feishu Streaming] _handle_reasoning_delta: not feishu adapter=%s chat_id=%s", adapter, chat_id)
        return
    if not should_stream(adapter, chat_id):
        logger.warning("[Feishu Streaming] _handle_reasoning_delta: should_stream=False, skipping")
        return

    # Guard: if thinking text is already populated (from either XML-tagged text in
    # send_or_edit OR from reasoning_content delta), don't re-accumulate from
    # reasoning_content here — that would double-count MiniMax which sends both.
    current_thinking = get_thinking_text(adapter, chat_id)
    if current_thinking:
        logger.info("[Feishu Streaming] _handle_reasoning_delta: thinking already populated (len=%d), skipping", len(current_thinking))
        return

    try:
        new_thinking = str(reasoning_text)
        remember_thinking_text(adapter, chat_id, new_thinking)

        # Worker thread has no running event loop, so use get_event_loop()
        # (safe here since we're scheduling coroutines, not blocking the loop)
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = None
        if loop is None or not loop.is_running():
            logger.warning("[Feishu Streaming] _handle_reasoning_delta: no event loop")
            return

        active_card_id = get_card_id(adapter, chat_id)
        logger.info("[Feishu Streaming] _handle_reasoning_delta: active_card=%s thinking_len=%d", active_card_id, len(new_thinking))
        if active_card_id:
            # Card exists — stream thinking text incrementally
            asyncio.run_coroutine_threadsafe(
                _stream_thinking_to_card(adapter, chat_id, active_card_id, new_thinking),
                loop,
            )
        else:
            # Card not created yet — eagerly create it so thinking can stream
            asyncio.run_coroutine_threadsafe(
                _ensure_card_for_reasoning(consumer, adapter, chat_id),
                loop,
            )
    except Exception as exc:
        logger.warning("reasoning delta handler error: %s", exc, exc_info=True)


async def _ensure_card_for_reasoning(
    consumer: Any,
    adapter: Any,
    chat_id: str,
) -> None:
    """Eagerly create the streaming card when reasoning arrives before text.

    Without this, reasoning_content deltas arrive before the first text token
    and have no card to stream into — all thinking text is buffered and only
    appears in one burst when the card is finally created.
    """
    from .streaming_support import resolve_reply_to_message_id

    state = get_chat_state(adapter, chat_id)
    if state.card_message_id or state.phase in ("streaming", "completed", "aborted", "terminated"):
        return

    expected_generation = _resolve_expected_generation(adapter, chat_id, owner=consumer)
    await _ensure_card_created(
        adapter,
        chat_id,
        reply_to=resolve_reply_to_message_id(consumer),
        metadata=getattr(consumer, "metadata", None),
        expected_generation=expected_generation,
    )


async def _stream_thinking_to_card(
    adapter: Any,
    chat_id: str,
    card_id: str,
    thinking_text: str,
) -> None:
    """Stream accumulated thinking text into the CardKit thinking panel element.

    Uses ``stream_card_content`` on ``THINKING_TEXT_ELEMENT_ID`` for real-time
    typewriter rendering.  Throttled to ``THINKING_THROTTLE_SECONDS`` to avoid
    overwhelming the CardKit API.
    """
    from .cardkit import stream_card_content
    from ..channel.runtime_state import advance_card_sequence, get_card_update_lock

    state = get_chat_state(adapter, chat_id)
    now = asyncio.get_running_loop().time()
    last = getattr(state, "last_thinking_update_at", 0.0) or 0.0
    if last > 0 and (now - last) < THINKING_THROTTLE_SECONDS:
        return
    state.last_thinking_update_at = now

    # Truncate to avoid sending massive thinking text every frame
    display_text = thinking_text[-3000:] if len(thinking_text) > 3000 else thinking_text

    try:
        async with get_card_update_lock(adapter, chat_id):
            sequence = advance_card_sequence(adapter, chat_id)
            await stream_card_content(
                adapter,
                card_id=card_id,
                element_id=THINKING_ELEMENT_ID,
                content=display_text,
                sequence=sequence,
            )
    except Exception as exc:
        # CardKit streaming failed — fall back to full-card update
        logger.warning("stream_thinking_to_card CardKit streaming failed, falling back to sync: %s", exc)
        try:
            await sync_thinking_card(adapter, chat_id, expected_generation=0)
        except Exception:
            pass


def patch_streaming_cards() -> bool:
    """Patch GatewayStreamConsumer to use CardKit-first streaming in Feishu."""
    import gateway.stream_consumer as stream_consumer

    if not getattr(original_on_delta, "__hermes_feishu_plugin_wrapped__", False):

        def wrapped_on_delta(self: Any, text: str | None, *, reasoning_content: str | None = None) -> None:
            # MiniMax sends reasoning_content without text (reasoning_only=True).
            # Suppressing these would drop all thinking from the stream.
            if text is None and reasoning_content is None:
                return
            return original_on_delta(self, text, reasoning_content=reasoning_content)

        wrapped_on_delta.__hermes_feishu_plugin_wrapped__ = True
        stream_consumer.GatewayStreamConsumer.on_delta = wrapped_on_delta

    # Suppress the default _flush_reasoning → send_reasoning_content path.
    # With CardKit streaming, thinking content is already streamed in real-time
    # via _handle_reasoning_delta → _stream_thinking_to_card. Sending a
    # separate reasoning message afterwards creates a duplicate "思考中" card.
    if not getattr(stream_consumer.GatewayStreamConsumer, "__hermes_feishu_flush_reasoning_patched__", False):
        _original_flush_reasoning = stream_consumer.GatewayStreamConsumer._flush_reasoning

        async def _patched_flush_reasoning(self: Any) -> None:
            if is_feishu_adapter(self.adapter) and should_stream(self.adapter, self.chat_id):
                # CardKit streaming already handled thinking — skip the default
                # send_reasoning_content path entirely.
                return
            return await _original_flush_reasoning(self)

        stream_consumer.GatewayStreamConsumer._flush_reasoning = _patched_flush_reasoning
        stream_consumer.GatewayStreamConsumer.__hermes_feishu_flush_reasoning_patched__ = True

    # Hook agent reasoning stream so DeepSeek / MiniMax reasoning_content
    # deltas flow into the CardKit thinking panel.  The agent fires
    # _fire_reasoning_delta from its worker thread; we route those into
    # remember_thinking_text + sync_thinking_card so the collapsible
    # thinking panel inside the card stays populated.
    if not getattr(stream_consumer.GatewayStreamConsumer, "__hermes_feishu_reasoning_hooked__", False):
        try:
            import run_agent as _run_agent
        except Exception:
            logger.warning("hermes_feishu_plugin reasoning hook skipped: cannot import run_agent")
        else:
            _original_fire_reasoning = _run_agent.AIAgent._fire_reasoning_delta

            def _patched_fire_reasoning(self: Any, text: str) -> None:
                _original_fire_reasoning(self, text)
                _handle_reasoning_delta(text, agent_id=id(self))

            _run_agent.AIAgent._fire_reasoning_delta = _patched_fire_reasoning
        stream_consumer.GatewayStreamConsumer.__hermes_feishu_reasoning_hooked__ = True

    if getattr(original_send_or_edit, "__hermes_feishu_plugin_wrapped__", False):
        return True

    async def wrapped_send_or_edit(self: Any, text: str, *, finalize: bool = False) -> bool:
        # Reset _has_card for a fresh streaming session (when _message_id is None)
        if getattr(self, '_message_id', None) is None:
            self._has_card = False
        cleaned = self._clean_for_display(text)
        logger.info("[Feishu Streaming] wrapped_send_or_edit ENTRY: chat=%s text_len=%d finalize=%s is_feishu=%s",
                    getattr(self, 'chat_id', '?'), len(cleaned), finalize,
                    is_feishu_adapter(self.adapter) if hasattr(self, 'adapter') else 'no_adapter')
        if not cleaned.strip():
            return False

        if not is_feishu_adapter(self.adapter):
            return await original_send_or_edit(self, text, finalize=finalize)
        if not should_stream(self.adapter, self.chat_id):
            return await original_send_or_edit(self, text, finalize=finalize)

        # Register this consumer in the thread map so the worker thread
        # (which fires reasoning deltas) can look it up safely even when
        # multiple chats are streaming concurrently.
        thread_key = threading.current_thread().ident
        _thread_consumer_map[thread_key] = self
        # Also register by agent id so the hooked _fire_reasoning_delta
        # (which has no thread context) can find the right consumer.
        if hasattr(self, "_agent") and self._agent is not None:
            _agent_consumer_map[id(self._agent)] = self
        # Drain any pending reasoning that arrived before this consumer
        # registered (MiniMax sends reasoning_content before the first text
        # delta). Use thread_key since that's what we buffered by.
        with _reasoning_delta_lock:
            pending = _pending_reasoning_by_thread.pop(thread_key, "")
        if pending:
            logger.info(
                "[Feishu Streaming] draining pending reasoning for thread=%s len=%d",
                thread_key, len(pending),
            )
            remember_thinking_text(self.adapter, self.chat_id, pending)

        logger.debug(
            "[Feishu Streaming] enter wrapped_send_or_edit chat=%s text_len=%d finalize=%s",
            self.chat_id, len(text or ""), finalize,
        )
        expected_generation = _resolve_expected_generation(self.adapter, self.chat_id, owner=self)
        if not _generation_matches(self.adapter, self.chat_id, expected_generation):
            logger.debug("[Feishu Streaming] gen mismatch, falling back chat=%s", self.chat_id)
            return False

        if should_suppress_status_message(cleaned):
            lines = parse_tool_progress_lines(cleaned)
            if lines:
                remember_tool_steps(self.adapter, self.chat_id, lines)
                await sync_progress_card(
                    self.adapter,
                    self.chat_id,
                    metadata=self.metadata,
                    expected_generation=expected_generation,
                )
            return True

        if cleaned == self._last_sent_text:
            return True

        # If the card was completed by a previous cursor-final turn, re-open it
        # for the next turn in a multi-turn agent loop.
        state = get_chat_state(self.adapter, self.chat_id)
        if state.phase == "completed":
            state.phase = "streaming"

        # Extract thinking content and accumulate it
        reasoning_raw, answer_raw = split_reasoning_text(cleaned)
        if reasoning_raw:
            current_thinking = get_thinking_text(self.adapter, self.chat_id)
            new_thinking = current_thinking + reasoning_raw
            remember_thinking_text(self.adapter, self.chat_id, new_thinking)

        # Always sync thinking panel if there's stored content (from on_reasoning_delta)
        # This ensures thinking from the reasoning channel also gets displayed
        thinking_content = get_thinking_text(self.adapter, self.chat_id)
        if thinking_content:
            await sync_thinking_card(
                self.adapter,
                self.chat_id,
                expected_generation=expected_generation,
            )
        # Use answer (stripped of thinking tags) as the visible text
        visible_text, cursor_is_final = strip_cursor(answer_raw, self.cfg.cursor)
        # cursor_is_final=True means this turn's text stream ended, but in multi-turn
        # agent loops more turns may follow. Only the gateway's finalize=True signal
        # should truly close the card. cursor_is_final triggers a content flush only.
        try:
            message_id = await _ensure_card_created(
                self.adapter,
                self.chat_id,
                reply_to=resolve_reply_to_message_id(self),
                metadata=self.metadata,
                expected_generation=expected_generation,
            )
            if not message_id:
                logger.info("[Feishu Streaming] _ensure_card_created returned None, fallback chat=%s", self.chat_id)
                return await original_send_or_edit(self, text, finalize=finalize)

            self._message_id = message_id
            self._has_card = True
            logger.info("[Feishu Streaming] card created msg_id=%s chat=%s finalize=%s", message_id, self.chat_id, finalize)
            remember_display_text(self.adapter, self.chat_id, visible_text)
            if finalize or cursor_is_final:
                if not await _finalize_card(
                    self.adapter,
                    self.chat_id,
                    visible_text,
                    expected_generation=expected_generation,
                    close_card=finalize,
                ):
                    logger.warning("[Feishu Streaming] _finalize_card failed, fallback chat=%s", self.chat_id)
                    return await original_send_or_edit(self, text, finalize=finalize)
            else:
                await _flush_answer(
                    self.adapter,
                    self.chat_id,
                    expected_generation=expected_generation,
                )
                # When cursor signals turn-end in a multi-turn stream, force a final
                # flush so the card shows this turn's complete answer before the next.
                if cursor_is_final and state.flush_controller:
                    state.flush_controller.complete()
                    await state.flush_controller.wait_for_flush()

            self._already_sent = True
            self._last_sent_text = cleaned
            logger.info("[Feishu Streaming] sent ok msg_id=%s chat=%s text_len=%d", self._message_id, self.chat_id, len(cleaned))
            return True
        except Exception as exc:
            logger.warning("[Feishu Streaming] CardKit streaming error: %s", exc)
            return False

    wrapped_send_or_edit.__hermes_feishu_plugin_wrapped__ = True
    stream_consumer.GatewayStreamConsumer._send_or_edit = wrapped_send_or_edit
    logger.info("[Feishu Streaming] patch_streaming_cards DONE")
    return True
