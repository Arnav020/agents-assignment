# Intelligent Interruption Handler

This project implements a context-aware interruption logic for LiveKit Agents. It distinguishes between "passive acknowledgement" (e.g., "yeah", "ok") and "active interruption" (e.g., "stop", "wait").

## How It Works

The solution uses a **Logic Layer** approach:
1.  **Manual Turn Detection**: The `AgentSession` is configured with `turn_detection="manual"`. This disables the default VAD-based interruption and turn committal.
2.  **`InterruptController`**: A custom class that listens to agent events (`user_input_transcribed`, `user_state_changed`, `agent_state_changed`).
3.  **Semantic Analysis**:
    - When the user speaks, the STT transcript is analyzed.
    - If the agent is **SPEAKING**:
        - "Soft" words (defined in `ignore_words` list) are **IGNORED**. The agent continues speaking.
        - "Command" words (defined in `command_words` list) trigger an **immediate interruption**.
        - Mixed sentences (e.g., "Yeah but wait") containing command words trigger an **interruption**.
    - If the agent is **SILENT**:
        - All input is treated as valid.

### Real-Time Guarantee

The interruption decision is made by reconciling:
- Fast VAD events (user started speaking)
- Slightly delayed STT transcripts (semantic meaning)

The controller buffers the interruption signal until STT is available and:
- Cancels it for soft acknowledgements
- Allows it immediately for semantic commands

This ensures:
- Zero audible pause or stutter on "yeah/ok"
- Immediate cutoff on "stop/wait"
- No modification of the low-level VAD kernel

## Usage

### Running the Agent

```bash
# Ensure you are in the examples/voice_agents directory
cd examples/voice_agents

# Run the intelligent agent in dev mode
python intelligent_agent.py dev
```

### Configuration

You can customize the `ignore_words` and `command_words` in `intelligent_agent.py`:

```python
controller = InterruptController(
    session,
    ignore_words=["yeah", "ok", "uh-huh"],
    command_words=["stop", "wait", "cancel"]
)
```

## Architecture

- **`intelligent_agent.py`**: The entrypoint. Sets up the `AgentSession` and wires the `InterruptController`.
- **`interrupt_controller.py`**: Contains the `InterruptController` class which implements the logic matrix.

## Logic Matrix

| User Input | Agent State | Behavior | Logic |
| :--- | :--- | :--- | :--- |
| "Yeah" / "Ok" | Speaking | **IGNORE** | Agent continues speaking. |
| "Stop" / "Wait" | Speaking | **INTERRUPT** | Agent stops immediately. |
| "Yeah" / "Ok" | Silent | **RESPOND** | Agent treats as valid input. |
| "Hello" | Silent | **RESPOND** | Normal behavior. |
| "Yeah wait" | Speaking | **INTERRUPT** | Mixed input treated as command. |

## Dependencies

- `livekit-agents`
- `livekit-plugins-deepgram` (for STT)
- `livekit-plugins-openai` (for LLM)
- `livekit-plugins-silero` (for VAD)

Ensure environment variables are set for these services.

## Verification

The following scenarios were tested:

1. **Long Explanation**
   - Agent speaking, user says "yeah", "uh-huh"
   - Result: Agent continues speaking (no pause, no stop)

2. **Passive Affirmation**
   - Agent silent, user says "yeah"
   - Result: Agent treats it as valid input and responds

3. **Correction**
   - Agent speaking, user says "stop"
   - Result: Agent stops immediately

4. **Mixed Input**
   - Agent speaking, user says "yeah but wait"
   - Result: Agent stops due to semantic command ("wait")

These scenarios demonstrate state-aware and semantic-aware interruption handling.
