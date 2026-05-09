import { detectBottle } from './bottleAliases.js';
import { normalizeText } from './text.js';

const POSITIVE_PATTERNS = [
  /\bgot\b/i,
  /\bgrabbed\b/i,
  /\bsecured\b/i,
  /\bfound\b/i,
  /\bscored\b/i,
  /\bpicked\s+up\b/i,
  /\bacquired\b/i,
  /\blanded\b/i,
  /\bcopped\b/i,
  /\bwalked\s+out\s+with\b/i
];

const NEGATIVE_PATTERNS = [
  /\bmissed\b/i,
  /\blooking\s+for\b/i,
  /\banyone\s+(seen|see|spot|spotted)\b/i,
  /\biso\b/i,
  /\btrade\b/i,
  /\btrading\b/i,
  /\bselling\b/i,
  /\bfor\s+sale\b/i,
  /\bfs\b/i,
  /\bft\b/i,
  /\bwish\s+i\s+(got|had|found)\b/i,
  /\bneed\b/i,
  /\bwant\b/i,
  /\bwhere\b/i
];

export function analyzeAllocationMessage(content) {
  const normalized = normalizeText(content);

  if (!normalized) {
    return { shouldPrompt: false, reason: 'empty' };
  }

  if (normalized.startsWith('/') || normalized.startsWith('!')) {
    return { shouldPrompt: false, reason: 'command-like' };
  }

  const bottle = detectBottle(normalized);

  if (!bottle) {
    return { shouldPrompt: false, reason: 'no-bottle' };
  }

  const positiveMatches = POSITIVE_PATTERNS.filter((pattern) => pattern.test(normalized));
  const negativeMatches = NEGATIVE_PATTERNS.filter((pattern) => pattern.test(normalized));
  let score = positiveMatches.length * 2 - negativeMatches.length * 3;

  if (content.includes('?')) score -= 2;
  if (/\btoday\b|\bin\b/.test(normalized)) score += 1;
  if (/\bat\b|\bfrom\b/.test(normalized)) score += 2;
  if (/^\s*(got|grabbed|secured|found|scored|picked up|acquired)\b/i.test(content)) score += 1;

  return {
    shouldPrompt: score >= 2,
    bottleName: bottle.bottleName,
    matchedAlias: bottle.matchedAlias,
    score,
    reason: score >= 2 ? 'likely-allocation' : 'low-confidence'
  };
}
