/**
 * Replaceable Speech Recognition & Synthesis Adapter for VaaniPay.
 * Interacts with browser Web Speech API (webkitSpeechRecognition / SpeechRecognition),
 * MediaDevices API (navigator.mediaDevices.getUserMedia / enumerateDevices),
 * and SpeechSynthesis API.
 * 
 * SAFETY & RELIABILITY GUARDS:
 * - Speech recognition is NOT proof of identity or authorization.
 * - Always abort/pause recognition before speech synthesis to prevent feedback loops.
 * - Proactively distinguishes between:
 *   1. Permission denial (NotAllowedError / not-allowed)
 *   2. Missing microphone hardware (NotFoundError / audio-capture / 0 audioinput devices)
 *   3. Microphone device busy / in-use by another app (NotReadableError / TrackStartError)
 *   4. Insecure context (non-HTTPS / non-localhost environments)
 *   5. Unsupported browser APIs (Firefox / older browsers lacking Web Speech)
 *   6. Harmless aborts and speech timeouts (no-speech, aborted)
 * - Always preserves the typed-input fallback for all states.
 */

export const SPEECH_ERROR_CODES = {
  INSECURE_CONTEXT: 'INSECURE_CONTEXT',
  UNSUPPORTED: 'UNSUPPORTED',
  NO_DEVICE: 'NO_DEVICE',
  PERMISSION_DENIED: 'PERMISSION_DENIED',
  DEVICE_BUSY: 'DEVICE_BUSY',
  SECURITY_ERROR: 'SECURITY_ERROR',
  NETWORK_ERROR: 'NETWORK_ERROR',
  SERVICE_DISALLOWED: 'SERVICE_DISALLOWED',
  AUDIO_CAPTURE_FAILED: 'AUDIO_CAPTURE_FAILED',
  NO_SPEECH: 'NO_SPEECH',
  START_FAILED: 'START_FAILED',
  UNKNOWN_ERROR: 'UNKNOWN_ERROR',
};

export function mapMediaError(err) {
  if (!err) {
    return {
      code: SPEECH_ERROR_CODES.UNKNOWN_ERROR,
      message: 'Unknown microphone error. Please use the typed input box.',
    };
  }

  const name = err.name || '';
  if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
    return {
      code: SPEECH_ERROR_CODES.PERMISSION_DENIED,
      message: 'Microphone permission was denied. Please allow microphone access in your browser site settings or use typed input.',
    };
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return {
      code: SPEECH_ERROR_CODES.NO_DEVICE,
      message: 'No microphone hardware found on your system. Please plug in a microphone or use typed input.',
    };
  }
  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return {
      code: SPEECH_ERROR_CODES.DEVICE_BUSY,
      message: 'Your microphone is currently in use by another application or blocked by system audio settings. Please close other audio apps or use typed input.',
    };
  }
  if (name === 'SecurityError') {
    return {
      code: SPEECH_ERROR_CODES.SECURITY_ERROR,
      message: 'Microphone access is restricted by security policy or insecure origin. Please use typed input.',
    };
  }

  return {
    code: SPEECH_ERROR_CODES.UNKNOWN_ERROR,
    message: `Microphone access failed (${name || err.message || 'error'}). Please use typed input.`,
  };
}

export class SpeechAdapter {
  constructor({ onTranscript, onStateChange, onError } = {}) {
    this.onTranscript = onTranscript || (() => {});
    this.onStateChange = onStateChange || (() => {});
    this.onError = onError || (() => {});

    this.recognition = null;
    this.isListening = false;
    this.isSupported = false;
    this.isSpeaking = false;
    this.currentTurnId = 0;
    this._isExplicitlyAborting = false;

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
        // SAFETY GUARD: Never use a transcript generated while the system TTS is speaking
        if (this.isSpeaking) {
          // If window.speechSynthesis is genuinely speaking, drop the audio to prevent feedback loops
          if (typeof window !== 'undefined' && window.speechSynthesis?.speaking) {
            return;
          }
          // Self-heal: flag was set but audio is no longer playing
          this.isSpeaking = false;
        }

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
        this._handleRecognitionError(event);
      };

      this.recognition.onend = () => {
        this.isListening = false;
        this.onStateChange('IDLE');
      };
    } catch (e) {
      this.isSupported = false;
    }
  }

  _handleRecognitionError(event) {
    this.isListening = false;

    // If the session was aborted programmatically or during stop, it is not an error
    if (event?.error === 'aborted' || this._isExplicitlyAborting) {
      this.onStateChange('IDLE');
      return;
    }

    // Handle no-speech timeout as an operational notice, not a fatal failure
    if (event?.error === 'no-speech') {
      this.onStateChange('IDLE');
      this.onError({
        code: SPEECH_ERROR_CODES.NO_SPEECH,
        message: 'No speech was detected before timeout. Please speak clearly into your microphone, or use typed input.',
      });
      return;
    }

    let code = SPEECH_ERROR_CODES.UNKNOWN_ERROR;
    let errorMessage = `Speech recognition error (${event?.error}). Please use typed input.`;

    if (event?.error === 'not-allowed') {
      code = SPEECH_ERROR_CODES.PERMISSION_DENIED;
      errorMessage = 'Microphone permission was denied or blocked by browser/system settings. Please allow microphone access or use typed input.';
    } else if (event?.error === 'audio-capture') {
      code = SPEECH_ERROR_CODES.AUDIO_CAPTURE_FAILED;
      errorMessage = 'Audio capture failed: No microphone device was found or the microphone is disconnected.';
    } else if (event?.error === 'network') {
      code = SPEECH_ERROR_CODES.NETWORK_ERROR;
      errorMessage = 'Network error contacting browser speech recognition service. Please check your internet connection or use typed input.';
    } else if (event?.error === 'service-not-allowed') {
      code = SPEECH_ERROR_CODES.SERVICE_DISALLOWED;
      errorMessage = 'Speech recognition service is disallowed by browser policy. Please use typed input.';
    }

    this.onStateChange('ERROR');
    this.onError({ code, message: errorMessage });
  }

  /**
   * Diagnostic check verifying context, device availability, and permissions.
   * Returns { ok: true } on success or { ok: false, code, message } on failure.
   */
  async verifyMicrophoneAccess() {
    // 1. Check for Web Speech API support
    if (!this.isSupported || !this.recognition) {
      return {
        ok: false,
        code: SPEECH_ERROR_CODES.UNSUPPORTED,
        message: 'Web Speech API is not supported in this browser (Chrome or Edge is recommended). Please use the typed input box below.',
      };
    }

    // 2. Check for insecure context (e.g. cloud HTTP)
    const isPotentiallyInsecure = typeof window !== 'undefined' && window.isSecureContext === false;

    // 3. Check for mediaDevices hardware & permission prompt
    if (typeof navigator !== 'undefined' && navigator.mediaDevices) {
      // Check device presence via enumerateDevices if supported
      if (typeof navigator.mediaDevices.enumerateDevices === 'function') {
        try {
          const devices = await navigator.mediaDevices.enumerateDevices();
          const audioInputs = devices.filter((d) => d.kind === 'audioinput');
          if (devices.length > 0 && audioInputs.length === 0) {
            return {
              ok: false,
              code: SPEECH_ERROR_CODES.NO_DEVICE,
              message: 'No microphone input hardware was detected on your system. Please connect a microphone or use typed input.',
            };
          }
        } catch (_) {
          // Fall through to getUserMedia
        }
      }

      // Check permission status via Permissions API if available
      if (navigator.permissions && typeof navigator.permissions.query === 'function') {
        try {
          const perm = await navigator.permissions.query({ name: 'microphone' });
          if (perm.state === 'denied') {
            return {
              ok: false,
              code: SPEECH_ERROR_CODES.PERMISSION_DENIED,
              message: 'Microphone permission is blocked in your browser site settings. Please click the icon in your address bar to allow microphone access, or use typed input.',
            };
          }
        } catch (_) {
          // Some browsers reject query for 'microphone', fall through to getUserMedia
        }
      }

      // Request media stream to prompt the user if permission is needed
      if (typeof navigator.mediaDevices.getUserMedia === 'function') {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          // Stop all stream tracks immediately after permission check so recognition can bind cleanly
          stream.getTracks().forEach((track) => track.stop());
        } catch (err) {
          const mapped = mapMediaError(err);
          if (isPotentiallyInsecure && (mapped.code === SPEECH_ERROR_CODES.SECURITY_ERROR || mapped.code === SPEECH_ERROR_CODES.PERMISSION_DENIED)) {
            return {
              ok: false,
              code: SPEECH_ERROR_CODES.INSECURE_CONTEXT,
              message: 'Microphone access is restricted on non-HTTPS cloud servers. Please access via HTTPS or use the typed input box below.',
            };
          }
          return {
            ok: false,
            code: mapped.code,
            message: mapped.message,
          };
        }
      }
    } else if (isPotentiallyInsecure) {
      return {
        ok: false,
        code: SPEECH_ERROR_CODES.INSECURE_CONTEXT,
        message: 'Microphone access is restricted on non-HTTPS cloud servers. Please access via HTTPS or use the typed input box below.',
      };
    }

    return { ok: true };
  }

  async startListening() {
    // Ensure TTS is cancelled before microphone activates
    this.stopSpeaking();

    if (this.isListening) {
      this.abortListening();
    }

    // Perform diagnostic verification
    const access = await this.verifyMicrophoneAccess();
    if (!access.ok) {
      this.onStateChange('ERROR');
      this.onError({
        code: access.code,
        message: access.message,
      });
      return false;
    }

    try {
      this._isExplicitlyAborting = false;
      this.recognition.start();
      return true;
    } catch (err) {
      // If already started (InvalidStateError), treat as listening
      if (err.name === 'InvalidStateError') {
        return true;
      }
      this.onStateChange('ERROR');
      this.onError({
        code: SPEECH_ERROR_CODES.START_FAILED,
        message: 'Could not activate microphone recognition. Please try again or use typed input.',
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
    this._isExplicitlyAborting = true;
    if (this.recognition && this.isListening) {
      try {
        this.recognition.abort();
      } catch (_) {}
    }
    this.isListening = false;
    this.onStateChange('IDLE');
    setTimeout(() => {
      this._isExplicitlyAborting = false;
    }, 50);
  }

  /**
   * Browser Text-to-Speech (TTS) for read-back synthesis.
   * INVARIANT: Always stops recognition prior to synthesis so the assistant's voice
   * is never transcribed as customer speech.
   */
  speak(text, onComplete = null) {
    if (typeof window === 'undefined' || !('speechSynthesis' in window)) {
      this.isSpeaking = false;
      if (onComplete) onComplete();
      return;
    }

    // 1. Abort any active speech listening immediately!
    this.abortListening();

    // 2. Clear any pending safety watchdog timer
    if (this._speakTimeout) {
      clearTimeout(this._speakTimeout);
      this._speakTimeout = null;
    }

    // 3. Cancel and resume speech synthesis to clear stuck audio pipelines
    try {
      window.speechSynthesis.cancel();
      window.speechSynthesis.resume();
    } catch (_) {}

    if (!text) {
      this.isSpeaking = false;
      if (onComplete) onComplete();
      return;
    }

    const utterance = new SpeechSynthesisUtterance(text);
    // Retain reference on instance to prevent Chrome V8 garbage-collecting the utterance mid-speech!
    this._activeUtterance = utterance;
    utterance.lang = 'en-IN';
    utterance.rate = 0.95; // Measured pace for financial clarity

    this.isSpeaking = true;

    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      this.isSpeaking = false;
      this._activeUtterance = null;
      if (this._speakTimeout) {
        clearTimeout(this._speakTimeout);
        this._speakTimeout = null;
      }
      if (onComplete) {
        try {
          onComplete();
        } catch (_) {}
      }
    };

    utterance.onend = finish;
    utterance.onerror = finish;

    // Safety watchdog: Chrome sometimes stalls or pauses synthesis without firing onend.
    // Calculate duration based on word count plus 2 seconds buffer.
    const words = text.split(/\s+/).length;
    const timeoutMs = Math.max(3000, Math.ceil((words / 2.0) * 1000) + 2000);
    this._speakTimeout = setTimeout(() => {
      finish();
    }, timeoutMs);

    try {
      window.speechSynthesis.speak(utterance);
      if (window.speechSynthesis.paused) {
        window.speechSynthesis.resume();
      }
    } catch (_) {
      finish();
    }
  }

  stopSpeaking() {
    this.isSpeaking = false;
    this._activeUtterance = null;
    if (this._speakTimeout) {
      clearTimeout(this._speakTimeout);
      this._speakTimeout = null;
    }
    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel();
      } catch (_) {}
    }
  }
}
