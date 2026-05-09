import { EmbedBuilder } from 'discord.js';
import { currentYear, getLeaderboardMessageId, setLeaderboardMessageId } from '../database.js';
import { getLatestAllocations, getServerTotal, getTopBottles, getTopHunters } from './allocationQueries.js';

function numberedRows(rows) {
  if (!rows.length) return 'No hunters on the board yet.';
  return rows.map((row, index) => `${index + 1}. ${row.username} — ${row.total}`).join('\n');
}

function latestRows(rows) {
  if (!rows.length) return 'No allocations logged yet.';
  return rows.map((row) => `• ${row.username} — ${row.bottle_name}`).join('\n');
}

function bottleRows(rows) {
  if (!rows.length) return 'No bottles logged yet.';
  return rows.map((row, index) => `${index + 1}. ${row.bottle_name} — ${row.total}`).join('\n');
}

export async function buildLeaderboardEmbed(guildId, year = currentYear()) {
  const [total, topHunters, latest, topBottles] = await Promise.all([
    getServerTotal(guildId, year),
    getTopHunters(guildId, year, 5),
    getLatestAllocations(guildId, year, 5),
    getTopBottles(guildId, year, 5)
  ]);

  return new EmbedBuilder()
    .setTitle(`🥃 ${year} Allocation Tracker`)
    .setColor(0xC9973A)
    .setDescription(`**Server Total:** ${total} bottle${total === 1 ? '' : 's'}`)
    .addFields(
      { name: 'Top Hunters', value: numberedRows(topHunters), inline: false },
      { name: 'Latest Allocations', value: latestRows(latest), inline: false },
      { name: 'Top Bottles', value: bottleRows(topBottles), inline: false }
    )
    .setFooter({ text: 'NeatBot Allocation Tracker · historical data is preserved by year' })
    .setTimestamp(new Date());
}

export async function updateLeaderboard(channel, year = currentYear()) {
  if (!channel?.guild) return null;

  const guildId = channel.guild.id;
  const channelId = channel.id;
  const embed = await buildLeaderboardEmbed(guildId, year);
  const existingId = await getLeaderboardMessageId({ guildId, channelId, year });

  if (existingId) {
    try {
      const message = await channel.messages.fetch(existingId);
      await message.edit({ embeds: [embed] });
      return message;
    } catch {
      // Message was deleted or can no longer be fetched; create a fresh persistent tally.
    }
  }

  const message = await channel.send({ embeds: [embed] });
  await setLeaderboardMessageId({ guildId, channelId, year, messageId: message.id });
  return message;
}
