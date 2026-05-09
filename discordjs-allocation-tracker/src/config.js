import 'dotenv/config';
import path from 'node:path';

export const config = {
  token: process.env.DISCORD_TOKEN,
  clientId: process.env.CLIENT_ID,
  guildId: process.env.GUILD_ID || null,
  trackerChannelName: process.env.ALLOCATION_TRACKER_CHANNEL_NAME || '🔢allocation-tracker',
  dbPath: process.env.ALLOCATION_DB_PATH || path.join(process.cwd(), 'allocations.db'),
  duplicateWindowHours: Number(process.env.ALLOCATION_DUPLICATE_WINDOW_HOURS || 6)
};

export function requireRuntimeConfig() {
  const missing = [];

  if (!config.token) missing.push('DISCORD_TOKEN');
  if (!config.clientId) missing.push('CLIENT_ID');

  if (missing.length) {
    throw new Error(`Missing required environment variable(s): ${missing.join(', ')}`);
  }
}
