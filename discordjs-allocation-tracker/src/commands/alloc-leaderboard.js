import { SlashCommandBuilder } from 'discord.js';
import { currentYear } from '../database.js';
import { buildLeaderboardEmbed } from '../services/leaderboard.js';

export const data = new SlashCommandBuilder()
  .setName('alloc-leaderboard')
  .setDescription('Show allocation tracker rankings.')
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
  const embed = await buildLeaderboardEmbed(interaction.guildId, year);
  await interaction.reply({ embeds: [embed], ephemeral: true });
}
