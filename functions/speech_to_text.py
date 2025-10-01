"""
Speech-to-Text module using pywhispercpp

Installation:
    pip install git+https://github.com/absadiki/pywhispercpp

(some other dependencies may be needed) 
"""

import threading
import queue
import time
import os
from typing import Callable, Optional, List
from pywhispercpp.examples.assistant import Assistant


class SimpleTTSController:
    """Simplified Text-to-Speech controller using pywhispercpp"""
    
    def __init__(self, on_text_received: Callable[[str], None], 
                 model='base.en', n_threads=8, silence_threshold=12, block_duration=30):
        self.on_text_received = on_text_received
        self.text_queue = queue.Queue()
        
        # Initialize the Assistant with voice recognition
        stderr = os.dup(2)
        os.close(2)
        os.open(os.devnull, os.O_RDWR)
        try:
            self.assistant = Assistant(
                model=model,
                commands_callback=self._queue_text,
                n_threads=n_threads,
                silence_threshold=silence_threshold,
                block_duration=block_duration,
            )
        except TypeError:
            self.assistant = Assistant(
                model=model,
                commands_callback=self._queue_text,
                n_threads=n_threads,
            )
        finally:
            os.dup2(stderr, 2)
            os.close(stderr)
        
        self.thread = None
        self.running = False

    def _queue_text(self, text: str):
        """Queue transcribed text for processing"""
        if isinstance(text, str) and text.strip():
            self.text_queue.put(text.strip())

    def start(self):
        """Start the voice recognition in a separate thread"""
        self.running = True
        self.thread = threading.Thread(target=self.assistant.start, daemon=True)
        self.thread.start()
        print("🎤 Voice recognition started")

    def get_latest_text(self) -> List[str]:
        """Get any new transcribed text from the queue"""
        texts = []
        try:
            while True:
                text = self.text_queue.get_nowait()
                texts.append(text)
        except queue.Empty:
            pass
        return texts

    def stop(self):
        """Stop the voice recognition"""
        self.running = False


class SpeechToText:
    """Main class for speech-to-text transcription"""
    
    def __init__(self, model='base.en', n_threads=8, silence_threshold=15, block_duration=30):
        self.tts_controller = SimpleTTSController(
            on_text_received=self._on_voice_text,
            model=model,
            n_threads=n_threads,
            silence_threshold=silence_threshold,
            block_duration=block_duration
        )
        self.transcription_history = []

    def _on_voice_text(self, text: str):
        """Callback when voice text is received"""
        print(f"Transcribed: {text}")
        
        # Store in transcription history
        self.transcription_history.append({
            "text": text,
            "timestamp": time.time()
        })

    def start(self):
        """Start the speech-to-text transcription"""
        self.tts_controller.start()
        print("Speech-to-text transcription started")

    def process_pending_audio(self):
        """Process any pending audio transcriptions (call this periodically)"""
        new_texts = self.tts_controller.get_latest_text()
        for text in new_texts:
            self._on_voice_text(text)

    def get_transcription_history(self) -> List[dict]:
        """Get the transcription history"""
        return self.transcription_history.copy()

    def stop(self):
        """Stop the transcription"""
        self.tts_controller.stop()
        print("Speech-to-text transcription stopped")


# Example usage
if __name__ == "__main__":
    # Initialize the speech-to-text transcriber
    transcriber = SpeechToText(model='base.en')
    
    try:
        # Start the transcriber
        transcriber.start()
        
        print("Speak into your microphone. The system will transcribe your speech.")
        print("Press Ctrl+C to stop...")
        
        while True:
            transcriber.process_pending_audio()
            time.sleep(0.5)  # Check every 500ms
            
    except KeyboardInterrupt:
        print("\nStopping...")
        transcriber.stop()
        
        # Print transcription history
        history = transcriber.get_transcription_history()
        if history:
            print("\nTranscription History:")
            for i, entry in enumerate(history, 1):
                print(f"{i}. {entry['text']}")

