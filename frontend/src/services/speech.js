/**
 * Replaceable Speech Recognition & Synthesis Adapter for VaaniPay.
 * Interacts with browser Web Speech API (webkitSpeechRecognition / SpeechRecognition)
 * and SpeechSynthesis API.
 * SAFETY GUARDS:
 * - Speech recognition is NOT proof of identity or authorization.
 * - Always abort/pause recognition before speech synthesis to prevent feedback loops.
 * - Graceful fallback when microphone permissions are denied or unsupported.
 */

export class SpeechAdapter {
  constructor({ onTranscript, onStateChange, onError } = {}) {
    this.onTranscript = onTranscript || (() => {});
    this.onStateChange = onStateChange || (() => {});
    this.onError = onError || (() => {});

    this.recognition = null;
    this.isListening = false;
    this.isSupported = false;

    this._initRecognition();
  }

  _initRecognition() {
    if (typeof window === 'undefined') {
      this.isSupported = false;
      return;
    }

    const SpeechRecognition =
      window.SpeechRecognition ||
      window.webkitSpeechRecognition ||
      null;

    if (!SpeechRecognition) {
      this.isSupported = false;
      return;
    }

    this.isSupported = true;
    try {
      this.recognition = new SpeechRecognition();
      this.recognition.continuous = false;
      this.recognition.interimResults = true;
      this.recognition.lang = 'en-IN'; // Optimized for Indian English & Hinglish

      this.recognition.onstart = () => {
        this.isListening = true;
        this.onStateChange('LISTENING');
      };

      this.recognition.onresult = (event) => {
        let interimTranscript = '';
        let finalTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; ++i) {
          const transcriptPiece = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            finalTranscript += transcriptPiece;
          } else {
            interimTranscript += transcriptPiece;
          }
        }

        const currentText = finalTranscript || interimTranscript;
        if (currentText) {
          this.onTranscript(currentText.trim(), Boolean(finalTranscript));
        }
      };

      this.recognition.onerror = (event) => {
        this.isListening = false;
        let errorMessage = 'Speech recognition error.';

        if (event.error === 'not-allowed') {
          errorMessage = 'Microphone permission denied. Please allow microphone access or use typed input.';
        } else if (event.error === 'no-speech') {
          errorMessage = 'No speech detected. Please speak clearly into your microphone.';
        } else if (event.error === 'audio-capture') {
          errorMessage = 'No microphone device found on your system.';
        } else if (event.error === 'network') {
          errorMessage = 'Network error during browser speech recognition. You can use typed input.';
        }

        this.onStateChange('ERROR');
        this.onError({ code: event.error, message: errorMessage });
      };

      this.recognition.onend = () => {
        this.isListening = false;
        this.onStateChange('IDLE');
      };
    } catch (e) {
      this.isSupported = false;
    }
  }

  startListening() {
    if (!this.isSupported || !this.recognition) {
      this.onError({
        code: 'UNSUPPORTED',
        message: 'Web Speech API is not supported in this browser. Please use the typed input box.',
      });
      return false;
    }

    // Ensure TTS is cancelled before microphone starts
    this.stopSpeaking();

    if (this.isListening) {
      try {
        this.recognition.abort();
      } catch (_) {}
    }

    try {
      this.recognition.start();
      return true;
    } catch (err) {
      this.onError({
        code: 'START_FAILED',
        message: 'Could not activate microphone. Please try again or use typed input.',
      });
      return false;
    }
  }

  stopListening() {
    if (this.recognition && this.isListening) {
      try {
        this.recognition.stop();
      } catch (_) {}
    }
    this.isListening = false;
    this.onStateChange('IDLE');
  }

  abortListening() {
    if (this.recognition && this.isListening) {
      try {
        this.recognition.abort();
      } catch (_) {}
    }
    this.isListening = false;
    this.onStateChange('IDLE');
  }

  /**
   * Browser Text-to-Speech (TTS) for read-back synthesis.
   * INVARIANT: Always stops recognition prior to synthesis so the assistant's voice
   * is never transcribed as customer speech.
   */
  speak(text, onComplete = null) {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      if (onComplete) onComplete();
      return;
    }

    // 1. Abort any active speech listening immediately!
    this.abortListening();

    // 2. Cancel prior ongoing speech utterances
    window.speechSynthesis.cancel();

    if (!text) {
      if (onComplete) onComplete();
      return;
    }

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = 'en-IN';
    utterance.rate = 0.95; // Slightly measured pace for financial clarity

    if (onComplete) {
      utterance.onend = () => onComplete();
      utterance.onerror = () => onComplete();
    }

    window.speechSynthesis.speak(utterance);
  }

  stopSpeaking() {
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      window.speechSynthesis.cancel();
    }
  }
}
