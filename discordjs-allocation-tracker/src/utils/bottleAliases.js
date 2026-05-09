import { compactForBoundary, escapeRegex, normalizeText } from './text.js';

export const BOTTLE_ALIASES = [
  {
    name: "Russell's Reserve 15 Year Bourbon",
    aliases: ['RR15', "Russell's 15", 'Russells 15', "Russell's Reserve 15", 'Russells Reserve 15']
  },
  {
    name: 'George T Stagg',
    aliases: ['GTS', 'George T. Stagg', 'George T Stagg', 'Stagg BTAC']
  },
  {
    name: 'William Larue Weller',
    aliases: ['WLW', 'William Larue', 'William Larue Weller']
  },
  {
    name: 'Eagle Rare 17 Year',
    aliases: ['ER17', 'Eagle Rare 17', 'Eagle Rare 17 Year']
  },
  {
    name: 'Thomas H Handy',
    aliases: ['THH', 'Handy', 'Thomas H. Handy', 'Thomas H Handy']
  },
  {
    name: 'Sazerac 18 Year',
    aliases: ['Saz18', 'Sazerac 18', 'Sazerac 18 Year']
  },
  {
    name: 'EH Taylor Barrel Proof',
    aliases: ['EHT BP', 'EH Taylor BP', 'E.H. Taylor BP', 'Taylor BP', 'EHT Barrel Proof']
  },
  {
    name: 'EH Taylor',
    aliases: ['EHT', 'EH Taylor', 'E.H. Taylor', 'Colonel Taylor']
  },
  {
    name: 'Jack Daniels 12 Year',
    aliases: ['JD12', "Jack Daniel's 12", 'Jack Daniels 12', 'JD 12']
  },
  {
    name: 'Jack Daniels 14 Year',
    aliases: ['JD14', "Jack Daniel's 14", 'Jack Daniels 14', 'JD 14']
  },
  {
    name: 'King of Kentucky',
    aliases: ['KoK', 'King of Kentucky']
  },
  {
    name: 'Old Weller Antique 107',
    aliases: ['OWA', 'Old Weller Antique', 'Old Weller Antique 107', 'Weller Antique', 'Weller Antique 107']
  },
  {
    name: 'Weller 12 Year',
    aliases: ['W12', 'Weller 12', 'Weller 12 Year']
  },
  {
    name: 'Weller CYPB',
    aliases: ['CYPB', 'Weller CYPB']
  },
  {
    name: 'Weller Full Proof',
    aliases: ['FP', 'WFP', 'Weller FP', 'Weller Full Proof', 'Full Proof']
  },
  {
    name: 'Stagg',
    aliases: ['Stagg', 'Stagg Jr', 'Stagg Jr.', 'Stagg Junior']
  }
];

const aliasEntries = BOTTLE_ALIASES.flatMap((bottle) => {
  const aliases = [bottle.name, ...bottle.aliases];
  return aliases.map((alias) => ({
    alias,
    normalizedAlias: normalizeText(alias),
    compactAlias: compactForBoundary(alias),
    name: bottle.name
  }));
}).sort((a, b) => b.compactAlias.length - a.compactAlias.length);

function aliasRegex(alias) {
  const normalized = normalizeText(alias);
  const flexible = escapeRegex(normalized).replace(/\\\s+/g, String.raw`\s+`);
  return new RegExp(`(^|\\b)${flexible}(\\b|$)`, 'i');
}

function compactContainsAlias(message, compactAlias) {
  if (compactAlias.length < 3) return false;
  const compactMessage = compactForBoundary(message);
  return compactMessage.includes(compactAlias);
}

export function detectBottle(messageContent) {
  const normalizedMessage = normalizeText(messageContent);

  for (const entry of aliasEntries) {
    if (aliasRegex(entry.normalizedAlias).test(normalizedMessage)) {
      return {
        bottleName: entry.name,
        matchedAlias: entry.alias
      };
    }

    if (compactContainsAlias(normalizedMessage, entry.compactAlias)) {
      return {
        bottleName: entry.name,
        matchedAlias: entry.alias
      };
    }
  }

  return null;
}
