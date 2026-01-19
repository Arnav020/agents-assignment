# Intelligent Interruption Agent - Solution Documentation

## Overview
This project implements a Voice Agent capability called **"Intelligent Interruption"** using LiveKit. The core goal is to distinguish between **backchanneling** (e.g., "yeah", "uh-huh") and **true interruptions** (e.g., "stop", "wait").

Standard voice agents typically interrupt TTS (Text-to-Speech) immediately upon detecting any user speech (VAD). This solution introduces a **buffering and classification layer** that delays the interruption decision until the speech content is transcribed and analyzed, triggering a stop only when semantic interruption is intended.

## Core Logic & Architecture

The solution modifies the standard `AgentActivity` lifecycle to introduce a verification gate.

### 1. Interception (VAD)
*   **File**: `examples/voice_agents/smart_interruption_session.py`
*   **Method**: `on_vad_inference_done`
*   **Logic**:
    *   Normally, VAD events trigger an immediate interruption of the agent's speech.
    *   We override this hook.
    *   If the agent is **silent**, we pass the event through (normal behavior).
    *   If the agent is **speaking**, we **suppress** the default interruption and instead **buffer** the VAD event in an internal queue (`pending_interruptions`).
    *   **Result**: The agent continues speaking while the user's audio is being processed.

### 2. Validation (STT & Classification)
*   **Files**: `examples/voice_agents/smart_interruption_session.py`, `examples/voice_agents/intelligent_interruption_agent.py`
*   **Methods**: `on_final_transcript`, `InterruptionClassifier.should_interrupt`
*   **Logic**:
    *   When the STT (Speech-to-Text) provider returns a final transcript, we check if there are pending buffered VAD events.
    *   The transcript is passed to the `InterruptionClassifier`.
    *   **Classification Rules**:
        *   **Ignore List**: Words like "yeah", "ok", "hmm" are classified as backchanneling.
        *   **Interrupt Keywords**: Words like "stop", "wait", "no" are classified as interruptions.
        *   **Semantic Override**: Complex phrases (e.g., "yeah but wait") containing interrupt keywords override the ignore list.

### 3. Decision Execution
*   **File**: `examples/voice_agents/smart_interruption_session.py`
*   **Methods**: `_execute_interruption`, `_discard_interruption`
*   **Logic**:
    *   **If Interrupt**: The buffered VAD event is "executed". The system calls `_interrupt_by_audio_activity()` to cut the TTS and the user's input is committed to the conversation context.
    *   **If Backchannel**: The buffered VAD event is "discarded". The TTS continues playing without a gap, and the user's input is optionally cleared or ignored to prevent the LLM from responding to "uh-huh".

---

## Key Files Implementation Details

### 1. `simualte_interruption_race.py` (Verification Harness)
This is a standalone script designed to prove the correctness of the race-condition logic without requiring real-time audio or paid APIs. It mocks the `AgentSession` and `Agent` dependencies.

*   **Purpose**: Simulates the exact timing delay between VAD (Voice Activity Detection) and STT (Speech-to-Text).
*   **Scenarios**:
    *   **Scenario A (Backchannel)**: User says "yeah" while agent speaks.
        *   *Result*: `ACTION: IGNORE`. Agent continues.
    *   **Scenario B (Interrupt)**: User says "stop" while agent speaks.
        *   *Result*: `ACTION: EXECUTE INTERRUPTION`. Agent stops.
    *   **Scenario C (Silent)**: User says "yeah" while agent is silent.
        *   *Result*: `RESPOND`. Normal processing, no buffering.
    *   **Scenario D (Mixed)**: User says "yeah but wait".
        *   *Result*: `ACTION: EXECUTE INTERRUPTION`. Semantic override works.
*   **Output**: Generates `interruption_log_proof.txt` with microsecond-precision logs.

### 2. `smart_interruption_session.py`
This class extends `AgentSession` and injects a custom `SmartAgentActivity`.

*   **`SmartInterruptionSession`**:
    *   Overrides `_update_activity` to ensure `SmartAgentActivity` is always used instead of the default `AgentActivity`.
*   **`SmartAgentActivity`**:
    *   **`pending_interruptions`**: A dictionary buffer storing VAD events that occurred while the agent was speaking.
    *   **`log_trace()`**: A deterministic logging tool added to prove the internal state transitions for verification.
    *   **`_interruption_timeout()`**: A safety fallback. If STT fails to return within `INTERRUPTION_TIMEOUT_MS` (default 400ms), it defaults to interrupting to prevent the agent from ignoring long user queries.

### 3. `intelligent_interruption_agent.py`
The main entry point and configuration hub.

*   **`InterruptionClassifier`**:
    *   Contains configurable `IGNORE_WORDS` and `INTERRUPT_KEYWORDS`.
    *   Methods: `should_interrupt(text, agent_speaking)`, `is_pure_backchanneling(text)`.
*   **`IntelligentInterruptionHandler`**:
    *   Connects the classifier to the session.
    *   Tracks agent state (Speaking vs Listening).

---

## Verification & Proof

A log proof file `interruption_log_proof.txt` is generated by the simulation. It demonstrates the system satisfies all constraints:

1.  **Zero-Gap Processing**: For backchannels ("yeah"), logging confirms `TTS CONTINUES (no gap)`, proving the agent never stopped speaking.
2.  **Deterministic Interruption**: For commands ("stop"), logging confirms `TTS STOPPED`, proving the interruption mechanism is still functional when needed.
3.  **Latency Handling**: The logs show the buffering duration (approx 200ms in simulation) where the VAD event was held in stasis waiting for STT qualification.

This solution ensures a natural conversational flow where the user can acknowledge the agent ("mhmm") without breaking the agent's train of thought, while retaining the ability to command the agent to stop instantly.
