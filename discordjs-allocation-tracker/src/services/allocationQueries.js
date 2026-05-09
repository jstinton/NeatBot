import { getDb } from '../database.js';

export async function getServerTotal(guildId, year) {
  const row = await getDb().get(
    'SELECT COUNT(*) AS total FROM allocations WHERE guild_id = ? AND year = ?',
    guildId,
    year
  );
  return row?.total || 0;
}

export async function getTopHunters(guildId, year, limit = 5) {
  return getDb().all(
    `SELECT user_id, username, COUNT(*) AS total
     FROM allocations
     WHERE guild_id = ? AND year = ?
     GROUP BY user_id, username
     ORDER BY total DESC, username COLLATE NOCASE ASC
     LIMIT ?`,
    guildId,
    year,
    limit
  );
}

export async function getLatestAllocations(guildId, year, limit = 5) {
  return getDb().all(
    `SELECT user_id, username, bottle_name, created_at
     FROM allocations
     WHERE guild_id = ? AND year = ?
     ORDER BY created_at DESC, id DESC
     LIMIT ?`,
    guildId,
    year,
    limit
  );
}

export async function getTopBottles(guildId, year, limit = 10) {
  return getDb().all(
    `SELECT bottle_name, COUNT(*) AS total
     FROM allocations
     WHERE guild_id = ? AND year = ?
     GROUP BY bottle_name
     ORDER BY total DESC, bottle_name COLLATE NOCASE ASC
     LIMIT ?`,
    guildId,
    year,
    limit
  );
}

export async function getUserStats(guildId, userId, year) {
  const total = await getDb().get(
    `SELECT COUNT(*) AS total
     FROM allocations
     WHERE guild_id = ? AND user_id = ? AND year = ?`,
    guildId,
    userId,
    year
  );

  const favorite = await getDb().get(
    `SELECT bottle_name, COUNT(*) AS total
     FROM allocations
     WHERE guild_id = ? AND user_id = ? AND year = ?
     GROUP BY bottle_name
     ORDER BY total DESC, bottle_name COLLATE NOCASE ASC
     LIMIT 1`,
    guildId,
    userId,
    year
  );

  const recent = await getDb().all(
    `SELECT bottle_name, created_at
     FROM allocations
     WHERE guild_id = ? AND user_id = ? AND year = ?
     ORDER BY created_at DESC, id DESC
     LIMIT 5`,
    guildId,
    userId,
    year
  );

  const rankings = await getDb().all(
    `SELECT user_id, COUNT(*) AS total
     FROM allocations
     WHERE guild_id = ? AND year = ?
     GROUP BY user_id
     ORDER BY total DESC, user_id ASC`,
    guildId,
    year
  );

  const rankIndex = rankings.findIndex((row) => row.user_id === userId);

  return {
    total: total?.total || 0,
    favorite,
    recent,
    rank: rankIndex >= 0 ? rankIndex + 1 : null
  };
}
