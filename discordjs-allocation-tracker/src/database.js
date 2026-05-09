import fs from 'node:fs';
import path from 'node:path';
import sqlite3 from 'sqlite3';
import { open } from 'sqlite';
import { config } from './config.js';

let db;

export async function initDb() {
  fs.mkdirSync(path.dirname(config.dbPath), { recursive: true });

  db = await open({
    filename: config.dbPath,
    driver: sqlite3.Database
  });

  await db.exec('PRAGMA journal_mode = WAL;');
  await db.exec('PRAGMA foreign_keys = ON;');
  await db.exec(`
    CREATE TABLE IF NOT EXISTS allocations (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      guild_id TEXT NOT NULL,
      channel_id TEXT NOT NULL,
      user_id TEXT NOT NULL,
      username TEXT NOT NULL,
      bottle_name TEXT NOT NULL,
      original_message TEXT NOT NULL,
      message_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      year INTEGER NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_allocations_year_user
      ON allocations (guild_id, year, user_id);

    CREATE INDEX IF NOT EXISTS idx_allocations_duplicate
      ON allocations (guild_id, user_id, bottle_name, created_at);

    CREATE TABLE IF NOT EXISTS tracker_state (
      guild_id TEXT NOT NULL,
      channel_id TEXT NOT NULL,
      year INTEGER NOT NULL,
      leaderboard_message_id TEXT,
      updated_at TEXT NOT NULL,
      PRIMARY KEY (guild_id, channel_id, year)
    );

    CREATE TABLE IF NOT EXISTS pending_allocations (
      pending_id TEXT PRIMARY KEY,
      guild_id TEXT NOT NULL,
      channel_id TEXT NOT NULL,
      user_id TEXT NOT NULL,
      username TEXT NOT NULL,
      bottle_name TEXT NOT NULL,
      original_message TEXT NOT NULL,
      message_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      expires_at TEXT NOT NULL
    );
  `);

  return db;
}

export function getDb() {
  if (!db) throw new Error('Database has not been initialized.');
  return db;
}

export function currentYear(date = new Date()) {
  return date.getFullYear();
}

export async function createPendingAllocation(data) {
  const database = getDb();
  await database.run(
    `INSERT INTO pending_allocations (
      pending_id, guild_id, channel_id, user_id, username, bottle_name,
      original_message, message_id, created_at, expires_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    data.pendingId,
    data.guildId,
    data.channelId,
    data.userId,
    data.username,
    data.bottleName,
    data.originalMessage,
    data.messageId,
    data.createdAt,
    data.expiresAt
  );
}

export async function getPendingAllocation(pendingId) {
  return getDb().get('SELECT * FROM pending_allocations WHERE pending_id = ?', pendingId);
}

export async function deletePendingAllocation(pendingId) {
  await getDb().run('DELETE FROM pending_allocations WHERE pending_id = ?', pendingId);
}

export async function cleanupExpiredPendingAllocations() {
  await getDb().run('DELETE FROM pending_allocations WHERE expires_at < ?', new Date().toISOString());
}

export async function hasRecentDuplicate({ guildId, userId, bottleName, sinceIso }) {
  const row = await getDb().get(
    `SELECT id FROM allocations
     WHERE guild_id = ? AND user_id = ? AND bottle_name = ? AND created_at >= ?
     ORDER BY created_at DESC LIMIT 1`,
    guildId,
    userId,
    bottleName,
    sinceIso
  );
  return Boolean(row);
}

export async function saveAllocation(data) {
  const createdAt = data.createdAt || new Date().toISOString();
  const year = currentYear(new Date(createdAt));

  const result = await getDb().run(
    `INSERT INTO allocations (
      guild_id, channel_id, user_id, username, bottle_name,
      original_message, message_id, created_at, year
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    data.guildId,
    data.channelId,
    data.userId,
    data.username,
    data.bottleName,
    data.originalMessage,
    data.messageId,
    createdAt,
    year
  );

  return result.lastID;
}

export async function getLeaderboardMessageId({ guildId, channelId, year }) {
  const row = await getDb().get(
    'SELECT leaderboard_message_id FROM tracker_state WHERE guild_id = ? AND channel_id = ? AND year = ?',
    guildId,
    channelId,
    year
  );
  return row?.leaderboard_message_id || null;
}

export async function setLeaderboardMessageId({ guildId, channelId, year, messageId }) {
  await getDb().run(
    `INSERT INTO tracker_state (guild_id, channel_id, year, leaderboard_message_id, updated_at)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(guild_id, channel_id, year) DO UPDATE SET
       leaderboard_message_id = excluded.leaderboard_message_id,
       updated_at = excluded.updated_at`,
    guildId,
    channelId,
    year,
    messageId,
    new Date().toISOString()
  );
}
