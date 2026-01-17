import logging
from dotenv import load_dotenv

from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    cli,
)
from livekit.plugins import deepgram, openai, silero
from interrupt_controller import InterruptController

logger = logging.getLogger("intelligent-agent")
logger.setLevel(logging.INFO)

load_dotenv()

server = AgentServer()

@server.rtc_session()
async def entrypoint(ctx: JobContext):
    # Initialize AgentSession with manual turn detection
    # We must allow_interruptions=True so that we can manually trigger interrupts
    session = AgentSession(
        allow_interruptions=True, 
        turn_detection="manual",
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(),
        llm=openai.LLM(),
    )
    
    # Initialize our InterruptController
    # You can customize words here
    controller = InterruptController(session)
    
    # Wire up the events
    session.on("user_input_transcribed", controller.on_user_input_transcribed)
    session.on("agent_state_changed", controller.on_agent_state_changed)
    session.on("user_state_changed", controller.on_user_state_changed)

    agent = Agent(
        instructions="You are a helpful assistant. If the user says 'yeah' or 'ok' while you are speaking, assume they are listening and continue. If they say it while you are silent, acknowledge it. If they say 'stop', stop immediately.",
    )
    
    await session.start(agent=agent, room=ctx.room)


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

server.setup_fnc = prewarm

if __name__ == "__main__":
    cli.run_app(server)
