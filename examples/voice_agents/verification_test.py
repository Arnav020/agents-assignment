import sys
from unittest.mock import MagicMock

# Mock livekit.agents BEFORE importing interrupt_controller
mock_agents = MagicMock()
sys.modules["livekit"] = MagicMock()
sys.modules["livekit.agents"] = mock_agents

# Mock the events we use
class MockEvent:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

mock_agents.UserInputTranscribedEvent = lambda **kwargs: MockEvent(**kwargs)
mock_agents.element_voice_activity = MagicMock()
# We need to ensure AgentSession generic type doesn't crash if imported
mock_agents.AgentSession = MagicMock

# Now import the controller
# We need to make sure the import inside interrupt_controller works
# interrupt_controller imports: AgentSession, UserInputTranscribedEvent, UserStateChangedEvent, AgentStateChangedEvent
# So we need to set them on mock_agents
mock_agents.UserInputTranscribedEvent = MagicMock
mock_agents.UserStateChangedEvent = MagicMock
mock_agents.AgentStateChangedEvent = MagicMock

# We also need to rewrite interrupt_controller.py import locally or rely on them being available
# Since interrupt_controller.py is in the same dir, we can import it.
# BUT, we need to ensure the mocks are set up correctly for what it expects.

# Let's redefine the mocks to behave like classes where needed
class EventMock:
    def __init__(self, **kwargs):
         self.__dict__.update(kwargs)

mock_agents.UserInputTranscribedEvent = EventMock
mock_agents.UserStateChangedEvent = EventMock
mock_agents.AgentStateChangedEvent = EventMock

from interrupt_controller import InterruptController

import asyncio
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("verification-test")

class MockSession:
    def __init__(self):
        self.interrupt_called = False
        self.commit_called = False
        self.clear_called = False
        self.turn_detection = "manual"

    async def interrupt(self):
        logger.info("MOCK: session.interrupt() called")
        self.interrupt_called = True

    def commit_user_turn(self):
        logger.info("MOCK: session.commit_user_turn() called")
        self.commit_called = True

    def clear_user_turn(self):
        logger.info("MOCK: session.clear_user_turn() called")
        self.clear_called = True

    def reset(self):
        self.interrupt_called = False
        self.commit_called = False
        self.clear_called = False

async def run_scenario(name, controller, session, agent_state, user_input, expected_action):
    logger.info(f"\n--- Running Scenario: {name} ---")
    session.reset()
    
    # Set Agent State
    state_ev = EventMock(old_state="initializing", new_state=agent_state)
    controller.on_agent_state_changed(state_ev)
    
    # Simulate User Input (STT)
    transcribed_ev = EventMock(
        transcript=user_input, 
        is_final=True, 
        language="en", 
        speaker_id="user"
    )
    controller.on_user_input_transcribed(transcribed_ev)
    
    # Determine Check based on expectation
    if expected_action == "INTERRUPT":
        # we need to wait briefly for the async task if created
        await asyncio.sleep(0.01)
        if session.interrupt_called:
            logger.info("PASS: Valid Interruption triggered immediately.")
        else:
            logger.error(f"FAIL: Expected Interruption, got None.")
            
    elif expected_action == "IGNORE":
        await asyncio.sleep(0.01)
        if session.interrupt_called:
            logger.error("FAIL: Triggered Interruption for Ignored word!")
        else:
            logger.info("PASS: No immediate interruption (Correct).")
            
    # Simulate End of Speech (VAD)
    user_state_ev = EventMock(old_state="speaking", new_state="listening")
    controller.on_user_state_changed(user_state_ev)
    
    # Check Commit/Clear
    if expected_action == "IGNORE":
        if session.clear_called:
             logger.info("PASS: User turn cleared (Ignored).")
        else:
             logger.warning("FAIL: User turn NOT cleared.")
    elif expected_action == "RESPOND" or expected_action == "INTERRUPT":
        if session.commit_called:
            logger.info("PASS: User turn committed (Response/Action triggered).")
        else:
            logger.error("FAIL: User turn NOT committed.")

async def main():
    session = MockSession()
    controller = InterruptController(session)
    
    # Scenario 1: Long Explanation (Ignore "yeah")
    await run_scenario(
        "Scenario 1: Long Explanation (Ignore 'yeah')",
        controller, session,
        agent_state="speaking",
        user_input="Yeah",
        expected_action="IGNORE"
    )
    
    # Scenario 2: Passive Affirmation (Respond when silent)
    await run_scenario(
        "Scenario 2: Passive Affirmation (Respond when silent)",
        controller, session,
        agent_state="listening",
        user_input="Yeah",
        expected_action="RESPOND"
    )

    # Scenario 3: Correction ("Stop" interrupts)
    await run_scenario(
        "Scenario 3: Correction ('Stop' interrupts)",
        controller, session,
        agent_state="speaking",
        user_input="Stop",
        expected_action="INTERRUPT"
    )
    
    # Scenario 4: Mixed Input ("Yeah wait" interrupts)
    await run_scenario(
        "Scenario 4: Mixed Input ('Yeah wait' interrupts)",
        controller, session,
        agent_state="speaking",
        user_input="Yeah wait",
        expected_action="INTERRUPT"
    )

if __name__ == "__main__":
    asyncio.run(main())
