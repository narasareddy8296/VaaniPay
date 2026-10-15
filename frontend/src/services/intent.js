/**
 * Deterministic Confirmation and Cancellation Intent Parser for VaaniPay Frontend.
 * Mirrors the backend safety invariants for English and Hinglish payment dialogues.
 * 
 * CRITICAL SAFETY RULES:
 * - A payment request (e.g., "send 500 to Ramesh") is NEVER a confirmation.
 * - Silence, background audio, or non-affirmative phrases are NEVER confirmation.
 * - Conflicting words (e.g., "yes but cancel", "haan nahi") are strictly AMBIGUOUS.
 * - Cancellation safely stops the payment flow.
 */

export const CONFIRMATION_INTENTS = {
  CONFIRM: 'CONFIRM',
  CANCEL: 'CANCEL',
  AMBIGUOUS: 'AMBIGUOUS',
  PAYMENT_REQUEST: 'PAYMENT_REQUEST',
  SILENCE: 'SILENCE',
  UNKNOWN: 'UNKNOWN',
};

const AFFIRMATIVE_EXACT = new Set([
  'yes', 'yep', 'yeah', 'sure', 'proceed', 'confirm', 'confirmed',
  'haan', 'han', 'ha', 'haanji', 'haan ji', 'sahi hai', 'theek hai',
  'bhejo', 'bhej do', 'kar do', 'kardo', 'transfer karo', 'chalega',
  'yes confirm', 'yes please', 'please confirm', 'confirm payment',
  'haan confirm', 'haan confirm karo', 'ha confirm karo', 'ha confirm',
  'sure confirm', 'i confirm', 'approved', 'approve',
]);

const NEGATIVE_EXACT = new Set([
  'no', 'nope', 'cancel', 'cancelled', 'stop', 'abort',
  'nahi', 'nahin', 'na', 'mat bhejo', 'ruk jao', 'ruko',
  'no cancel', 'no please cancel', 'please cancel', 'cancel payment',
  'nahi cancel', 'nahi cancel karo', 'nahin cancel karo', 'mat karo',
  'do not send', 'dont send', "don't send", 'roko', 'ruko mat bhejo',
]);

const AFFIRMATIVE_TOKENS = [
  /\byes\b/, /\bconfirm\b/, /\bproceed\b/, /\bhaan\b/, /\bhan\b/,
  /\btheek hai\b/, /\bapproved\b/, /\bapprove\b/,
];

const NEGATIVE_TOKENS = [
  /\bno\b/, /\bcancel\b/, /\bstop\b/, /\babort\b/, /\bnahi\b/, /\bnahin\b/,
  /\bmat bhejo\b/, /\bruk jao\b/, /\bruko\b/, /\bdo not send\b/, /\bdont send\b/,
  /\bmat karo\b/, /\broko\b/,
];

const PAYMENT_PATTERNS = [
  /\b\d+\b/,
  /\b(?:send|transfer|pay|bhejo|bhej do|भेज|भेजो)\s+\d+/,
  /(?:sau|so|hazaar|hazar|lakh|lac|crore|dedh|dhai|sawa|paune|saade|bees|tees|chaalees|pachaas|saath|sattar|assi|nabbe|rupaye|rupees|rs|inr|डेढ़|ढाई|सवा|पौने|साढ़े|सौ|हज़ार|हजार|लाख|करोड़|बीस|तीस|चालीस|पचास|साठ|सत्तर|अस्सी|नब्बे|रुपये|रुपए|रु)/i,
];

const AMBIGUOUS_PATTERNS = [
  /\bmaybe\b/, /\bnot sure\b/, /\bwait\b/, /\bsoch raha\b/,
  /\bya\b/, /\beither\b/, /\bdoubt\b/, /\bconfusion\b/,
];

export function normalizeIntentText(text) {
  if (!text) return '';
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{M}\p{N}\s\-]/gu, ' ')
    .trim()
    .replace(/\s+/g, ' ');
}

export function parseConfirmationIntent(rawText) {
  const normalized = normalizeIntentText(rawText);

  // 1. Silence check
  if (!normalized) {
    return {
      intent: CONFIRMATION_INTENTS.SILENCE,
      confidence: 1.0,
      rawText: rawText || '',
      normalizedText: '',
      explanation: 'Empty or silence utterance.',
    };
  }

  // 2. Exact negative match
  if (NEGATIVE_EXACT.has(normalized)) {
    return {
      intent: CONFIRMATION_INTENTS.CANCEL,
      confidence: 1.0,
      rawText: rawText || '',
      normalizedText: normalized,
      explanation: `Explicit cancellation matched: "${normalized}".`,
    };
  }

  // 3. Exact affirmative match
  if (AFFIRMATIVE_EXACT.has(normalized)) {
    return {
      intent: CONFIRMATION_INTENTS.CONFIRM,
      confidence: 1.0,
      rawText: rawText || '',
      normalizedText: normalized,
      explanation: `Explicit confirmation matched: "${normalized}".`,
    };
  }

  const hasPaymentIndicator = PAYMENT_PATTERNS.some((re) => re.test(normalized));
  const hasNegToken = NEGATIVE_TOKENS.some((re) => re.test(normalized));
  const hasAffToken = AFFIRMATIVE_TOKENS.some((re) => re.test(normalized)) ||
    (!hasNegToken && /\b(?:bhejo|bhej do|kar do|kardo)\b/.test(normalized));

  // 4. Payment phrase check (SAFETY INVARIANT: payment request is never confirmation)
  if (hasPaymentIndicator) {
    if (hasNegToken) {
      return {
        intent: CONFIRMATION_INTENTS.CANCEL,
        confidence: 0.95,
        rawText: rawText || '',
        normalizedText: normalized,
        explanation: `Cancellation associated with payment phrase: "${normalized}".`,
      };
    }
    return {
      intent: CONFIRMATION_INTENTS.PAYMENT_REQUEST,
      confidence: 0.95,
      rawText: rawText || '',
      normalizedText: normalized,
      explanation: `Payment request detected instead of confirmation: "${normalized}".`,
    };
  }

  // 5. Conflicting tokens
  if (hasAffToken && hasNegToken) {
    return {
      intent: CONFIRMATION_INTENTS.AMBIGUOUS,
      confidence: 0.95,
      rawText: rawText || '',
      normalizedText: normalized,
      explanation: 'Conflicting affirmative and negative tokens detected.',
    };
  }

  // 6. Ambiguous patterns
  for (const pat of AMBIGUOUS_PATTERNS) {
    if (pat.test(normalized)) {
      return {
        intent: CONFIRMATION_INTENTS.AMBIGUOUS,
        confidence: 0.85,
        rawText: rawText || '',
        normalizedText: normalized,
        explanation: 'Ambiguity marker detected.',
      };
    }
  }

  // 7. Token-level detection
  if (hasNegToken) {
    return {
      intent: CONFIRMATION_INTENTS.CANCEL,
      confidence: 0.95,
      rawText: rawText || '',
      normalizedText: normalized,
      explanation: 'Cancellation token detected.',
    };
  }

  if (hasAffToken) {
    return {
      intent: CONFIRMATION_INTENTS.CONFIRM,
      confidence: 0.95,
      rawText: rawText || '',
      normalizedText: normalized,
      explanation: 'Confirmation token detected.',
    };
  }

  // 8. Default
  return {
    intent: CONFIRMATION_INTENTS.UNKNOWN,
    confidence: 0.5,
    rawText: rawText || '',
    normalizedText: normalized,
    explanation: 'Unrecognized utterance.',
  };
}
