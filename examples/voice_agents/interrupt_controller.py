import logging
import re
from typing import List, Optional

from livekit.agents import AgentSession, UserInputTranscribedEvent, UserStateChangedEvent, AgentStateChangedEvent

logger = logging.getLogger("interrupt-controller")

class InterruptController:
    def __init__(
        self, 
        session: AgentSession, 
        ignore_words: Optional[List[str]] = None, 
        command_words: Optional[List[str]] = None
    ):
        self.session = session
        self.ignore_words = set(ignore_words or ["yeah", "ok", "hmm", "uh-huh", "right", "okay"])
        # Command words that should forcefully trigger an interruption even if mixed with ignore words
        self.command_words = set(command_words or ["stop", "wait", "no", "cancel", "hold on"])
        
        self.is_agent_speaking = False
        self.current_transcript = ""
        self.interrupted_current_turn = False
        
        # Compile regex for faster cleaning
        self.clean_pattern = re.compile(r'[^\w\s]')

    def _clean_text(self, text: str) -> str:
        """Normalize text: lowercase, remove punctuation, strip."""
        return self.clean_pattern.sub('', text).lower().strip()

    def _should_interrupt(self, text: str) -> bool:
        """
        Determine if the current text should trigger an interruption while agent is speaking.
        Returns True if we should INTERRUPT, False if we should IGNORE.
        """
        cleaned_text = self._clean_text(text)
        if not cleaned_text:
            return False

        # Check for hard commands first ("semantic interruption")
        # If the text contains any command word, we must interrupt.
        # Simple containment check:
        # e.g. "yeah wait" -> contains "wait" -> Interrupt.
        for cmd in self.command_words:
            if cmd in cleaned_text:
                return True

        # Check for ignore words
        # If the text consists ONLY of ignore words, we should IGNORE (return False).
        # e.g. "yeah" -> subset of ignore -> False.
        # e.g. "yeah sure" -> "sure" not in ignore -> True (Interrupt).
        words = set(cleaned_text.split())
        if words.issubset(self.ignore_words):
            return False

        # Default: If it contains anything else, it's a valid sentence -> Interrupt.
        return True

    def on_agent_state_changed(self, ev: AgentStateChangedEvent):
        if ev.new_state == "speaking":
            self.is_agent_speaking = True
            self.interrupted_current_turn = False
        elif ev.new_state == "listening":
            self.is_agent_speaking = False

    def on_user_input_transcribed(self, ev: UserInputTranscribedEvent):
        transcript = ev.transcript
        self.current_transcript = transcript # Keep tracking full transcript
        
        # LOGIC:
        # If agent is NOT speaking, we don't need to 'interrupt'. 
        # We just wait for VAD end to commit.
        if not self.is_agent_speaking:
            return

        # If agent IS speaking:
        if self.interrupted_current_turn:
            return # Already interrupted this turn
            
        if self._should_interrupt(transcript):
            logger.info(f"Interrupting for: '{transcript}'")
            # Trigger interruption immediately
            # We don't await this because we are in a sync callback (or async wrapper)
            # but AgentSession.interrupt returns a future. Ideally we just fire and forget or schedule it.
            # But since we are likely in a callback loop, scheduling is safer if not async.
            # However events in this framework might be called from async context.
            # Let's check typical usage. usually callbacks are simple.
            # We can use asyncio.create_task if we are in a running loop.
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.session.interrupt())
                self.interrupted_current_turn = True
            except RuntimeError:
                logger.warning("No running loop to schedule interrupt")

    def on_user_state_changed(self, ev: UserStateChangedEvent):
        # We only care when user STOPS speaking (listening), which signals end of turn/utterance
        if ev.new_state == "listening":
            self._handle_end_of_turn()

    def _handle_end_of_turn(self):
        """
        Called when VAD detects silence. We must decide to COMMIT or DISCARD the turn.
        """
        transcript = self.current_transcript
        
        # Logic Matrix
        
        if self.interrupted_current_turn:
            self.session.commit_user_turn()
        elif self.is_agent_speaking:
            if self._should_interrupt(transcript):
                self.session.commit_user_turn()
            else:
                self.session.clear_user_turn()
        else:
            self.session.commit_user_turn()
            
        # Reset transcript for next turn
        self.current_transcript = ""
