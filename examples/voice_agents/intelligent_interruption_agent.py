import asyncio
import logging
import os
from typing import Set

from livekit.agents import (
    Agent,
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
)
from livekit.agents.voice import AgentSession
from livekit.agents.voice.audio_recognition import TurnDetectionMode
from livekit.plugins import deepgram, openai, silero
from livekit.agents.voice.events import AgentStateChangedEvent, UserInputTranscribedEvent

# Configure logging
logger = logging.getLogger("intelligent-interruption")
logger.setLevel(logging.INFO)

class AgentStateTracker:
    """Monitors agent speech state for context-aware interruption handling"""
    
    def __init__(self):
        self.is_speaking = False
        self._lock = asyncio.Lock()
    
    async def on_agent_state_changed(self, is_speaking: bool):
        async with self._lock:
            self.is_speaking = is_speaking
            logger.debug(f"Agent speaking state changed to: {self.is_speaking}")
    
    def is_agent_speaking(self) -> bool:
        """Thread-safe check of current agent state"""
        return self.is_speaking

class InterruptionClassifier:
    """Classifies user input as backchanneling vs interruption"""
    
    # Configurable word lists
    IGNORE_WORDS = {
        'yeah', 'yep', 'yes',
        'ok', 'okay', 'k',
        'hmm', 'mhmm', 'mm-hmm',
        'uh-huh', 'aha', 'right',
        'sure', 'alright'
    }
    
    INTERRUPT_KEYWORDS = {
        'stop', 'wait', 'hold', 'pause',
        'no', 'nope',
        'hang on', 'hold on', 'hold up'
    }
    
    def __init__(self, ignore_words=None, interrupt_keywords=None):
        if ignore_words:
            self.IGNORE_WORDS = set(ignore_words)
        if interrupt_keywords:
            self.INTERRUPT_KEYWORDS = set(interrupt_keywords)

    def should_interrupt(self, transcript: str, agent_speaking: bool) -> bool:
        """
        Decision logic:
        1. If agent is silent -> always process input (return True)
        2. If agent is speaking:
           - Contains interrupt keyword -> interrupt (return True)
           - Only contains ignore words -> don't interrupt (return False)
           - Mixed/unknown -> interrupt to be safe (return True)
        """
        if not agent_speaking:
            # Agent is silent, all user input is valid
            return True
        
        # Agent is speaking - classify the input
        text = transcript.lower().strip()
        tokens = set(text.split())
        
        # Check for explicit interrupt keywords (Token based)
        # We handle multi-word keywords by checking if any keyword phrase is present in text
        # But for primary token matching as requested:
        if tokens & self.INTERRUPT_KEYWORDS:
             logger.info(f"Interrupt keyword detected in: '{text}'")
             return True

        # Fallback for phrases like "hold on" if not in tokens (though prompt said token matched)
        # We will strictly follow the token intersection for the single words in INTERRUPT_KEYWORDS
        # If INTERRUPT_KEYWORDS contains phrases, we might need check:
        for keyword in self.INTERRUPT_KEYWORDS:
            if " " in keyword and keyword in text:
                logger.info(f"Interrupt phrase detected: '{keyword}'")
                return True

        # Check if it's ONLY backchanneling words
        if tokens and tokens.issubset(self.IGNORE_WORDS):
            logger.info(f"Pure backchanneling detected: '{text}' - ignoring")
            return False
        
        # Mixed content or unknown - err on side of interrupting
        logger.info(f"Mixed/unknown input: '{text}' - allowing interrupt")
        return True

class IntelligentInterruptionHandler:
    """
    Main handler that integrates state tracking and classification
    to provide intelligent interruption control
    """
    
    def __init__(self, ignore_words=None, interrupt_keywords=None):
        self.state_tracker = AgentStateTracker()
        self.classifier = InterruptionClassifier(ignore_words, interrupt_keywords)
    
    async def on_agent_state_changed(self, event: AgentStateChangedEvent):
        """Hook: Called when agent state changes"""
        # "speaking" state in LiveKit agents means the agent is currently outputting audio
        is_speaking = event.new_state == "speaking"
        await self.state_tracker.on_agent_state_changed(is_speaking)
    
    async def handle_user_transcript(
        self, 
        event: UserInputTranscribedEvent,
        session
    ) -> bool:
        """
        Process user transcript and decide interruption behavior.
        """
        transcript = event.transcript
        is_speaking = self.state_tracker.is_agent_speaking()
        should_interrupt = self.classifier.should_interrupt(transcript, is_speaking)
        
        logger.info(
            f"Transcript: '{transcript}' | "
            f"Agent speaking: {is_speaking} | "
            f"Should interrupt: {should_interrupt}"
        )
        
        if is_speaking:
            if should_interrupt:
                # Real interruption - stop the agent
                # Note: session.interrupt() stops the current audio playback
                # Since we are in manual mode, we should also likely commit the turn so the agent responds
                # But interrupt usually just stops TTS.
                # If we want the agent to RESPOND to the interruption (e.g. "Okay stopping"), 
                # we need to commit the turn.
                
                # However, usually session.interrupt() is for stopping previous output.
                # If we want to process the NEW input (the interruption command), we MUST commit it.
                await session.commit_user_turn()
                logger.info("Interruption executed & turn committed")
                return True
            else:
                # Backchanneling - ignore
                # In manual turn detection, if we don't commit, the agent typically ignores it.
                # But to be safe and clean the buffer, we can clear.
                # Use clear_user_turn directly on the session assuming verified existence.
                if hasattr(session, 'clear_user_turn'):
                     await session.clear_user_turn()
                logger.info("Backchanneling ignored - agent continues")
                return False
        else:
            # Agent is silent - commit the turn (normal processing)
            await session.commit_user_turn()
            logger.info("Valid input during silence - processing")
            return True

async def entrypoint(ctx: JobContext):
    # Load env vars for configuration
    ignore_words = os.getenv('IGNORE_WORDS', '').split(',') if os.getenv('IGNORE_WORDS') else None
    interrupt_keywords = os.getenv('INTERRUPT_KEYWORDS', '').split(',') if os.getenv('INTERRUPT_KEYWORDS') else None
    
    # Remove empty strings if any
    if ignore_words: ignore_words = [w.strip() for w in ignore_words if w.strip()]
    if interrupt_keywords: interrupt_keywords = [w.strip() for w in interrupt_keywords if w.strip()]

    # Initialize handler
    handler = IntelligentInterruptionHandler(ignore_words, interrupt_keywords)
    
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    
    

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model="nova-3"),
        llm=openai.LLM(model="gpt-4o-mini"),
        tts=openai.TTS(voice="echo"),
        turn_detection=TurnDetectionMode.MANUAL,
        allow_interruptions=True, # Critical for manual control
    )
    
    agent_logic = Agent(
        instructions="You are a helpful assistant. You will be interrupted effectively.",
    )

    # Attach Event Handlers
    @session.on("agent_state_changed")
    async def on_agent_state_changed(event: AgentStateChangedEvent):
        await handler.on_agent_state_changed(event)
    
    @session.on("user_input_transcribed")
    async def on_user_input_transcribed(event: UserInputTranscribedEvent):
        # We need to act on the session
        await handler.handle_user_transcript(event, session)

    session.start(agent=agent_logic, room=ctx.room)
    
    # Wait for the job to finish (this keeps the process alive)
    # Usually we await session.start?
    # agent_session.py start method is async.
    # await session.start(...)
    
    await session.start(agent=agent_logic, room=ctx.room)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
