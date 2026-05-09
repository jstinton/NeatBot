export function normalizeText(value) {
  return String(value || '')
    .toLowerCase()
    .replace(/[’‘]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/[^a-z0-9+#.\s'-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function escapeRegex(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export function compactForBoundary(value) {
  return normalizeText(value).replace(/[^a-z0-9]/g, '');
}
