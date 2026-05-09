import { EmbedBuilder, SlashCommandBuilder } from 'discord.js';
import { currentYear } from '../database.js';
import { getUserStats } from '../services/allocationQueries.js';

function recentRows(rows) {
  if (!rows.length) return 'No recent pickups for this year.';
  return rows.map((row) => `• ${row.bottle_name}`).join('\n');
}

export const data = new SlashCommandBuilder()
  .setName('alloc-stats')
  .setDescription('Show your allocation tracker stats.')
  .addIntegerOption((option) =>
    option
      .setName('year')
      .setDescription('Year to view, e.g. 2025')
      .setMinValue(2020)
      .setMaxValue(2100)
      .setRequired(false)
  );

export async function execute(interaction) {
  const year = interaction.options.getInteger('year') || currentYear();
  const stats = await getUserStats(interaction.guildId, interaction.user.id, year);

  const embed = new EmbedBuilder()
    .setTitle(`🥃 ${year} Allocation Stats`)
    .setColor(0xC9973A)
    .setDescription(`${interaction.user} allocation report`)
    .addFields(
      { name: 'Total Allocations', value: String(stats.total), inline: true },
      { name: 'Ranking', value: stats.rank ? `#${stats.rank}` : 'Unranked', inline: true },
      { name: 'Favorite Bottle', value: stats.favorite ? `${stats.favorite.bottle_name} (${stats.favorite.total})` : 'None yet', inline: false },
      { name: 'Recent Pickups', value: recentRows(stats.recent), inline: false }
    )
    .setTimestamp(new Date());

  await interaction.reply({ embeds: [embed], ephemeral: true });
}
