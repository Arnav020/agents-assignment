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

## Setup

### 1. Install Dependencies

You need `livekit-agents` and the implementation plugins:

```bash
pip install livekit-agents livekit-plugins-openai livekit-plugins-deepgram livekit-plugins-silero python-dotenv keyrings-alt
```

### 2. Configure Environment

1.  Create a `.env` file in the project root:
    ```env
    LIVEKIT_URL=wss://your-project.livekit.cloud
    LIVEKIT_API_KEY=your_key
    LIVEKIT_API_SECRET=your_secret
    OPENAI_API_KEY=sk-proj-...
    DEEPGRAM_API_KEY=...
    ```
    *(Refer to `.env.example` for a template)*

### 3. Run the Agent

Navigate to `examples/voice_agents` and run in development mode:

```bash
python intelligent_agent.py dev
```

## Architecture

- **`intelligent_agent.py`**: 
    - Entrypoint for the agent.
    - Configures `AgentSession` with `turn_detection="manual"`.
    - Initializes STT (Deepgram), LLM (OpenAI), and **TTS (OpenAI)**.
    - Implements an `on_enter` hook to greet the user immediately upon connection.
    - Wires up the `InterruptController`.
- **`interrupt_controller.py`**: 
    - Contains the `InterruptController` logic layer.
    - Implements phrase-aware command detection and race-safe turn committal.

## Interruption Logic Matrix

| User Input | Agent State | Behavior | Logic |
| :--- | :--- | :--- | :--- |
| "Yeah" / "Ok" | Speaking | **IGNORE** | Agent continues speaking. |
| "Stop" / "Wait" | Speaking | **INTERRUPT** | Agent stops immediately. |
| "Yeah" / "Ok" | Silent | **RESPOND** | Agent treats as valid input. |
| "Hello" | Silent | **RESPOND** | Normal behavior. |
| "Yeah wait" | Speaking | **INTERRUPT** | Mixed input treated as command. |

## Verification

The following scenarios were verified using `verification_test.py`:

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
