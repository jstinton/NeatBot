import crypto from 'node:crypto';
import { ActionRowBuilder, ButtonBuilder, ButtonStyle, EmbedBuilder, Events } from 'discord.js';
import { config } from '../config.js';
import { cleanupExpiredPendingAllocations, createPendingAllocation } from '../database.js';
import { analyzeAllocationMessage } from '../utils/detector.js';

function isTrackerChannel(message) {
  return message.channel?.name === config.trackerChannelName;
}

function confirmationRow(pendingId) {
  return new ActionRowBuilder().addComponents(
    new ButtonBuilder()
      .setCustomId(`alloc_confirm:${pendingId}`)
      .setLabel('Confirm')
      .setEmoji('✅')
      .setStyle(ButtonStyle.Success),
    new ButtonBuilder()
      .setCustomId(`alloc_cancel:${pendingId}`)
      .setLabel('Cancel')
      .setEmoji('❌')
      .setStyle(ButtonStyle.Secondary)
  );
}

function confirmationEmbed({ bottleName, matchedAlias, score }) {
  return new EmbedBuilder()
    .setTitle('🥃 Log this allocation?')
    .setColor(0xC9973A)
    .setDescription(`I think you acquired **${bottleName}**.`)
    .addFields(
      { name: 'Matched', value: matchedAlias || bottleName, inline: true },
      { name: 'Confidence', value: String(score), inline: true }
    )
    .setFooter({ text: 'Confirm to add it to the annual allocation tracker.' });
}

export const name = Events.MessageCreate;

export async function execute(message) {
  if (!message.guild || message.author.bot) return;
  if (!isTrackerChannel(message)) return;
  if (!message.content?.trim()) return;
  if (message.content.trim().startsWith('/') || message.content.trim().startsWith('!')) return;
  if (message.reference) return;

  const analysis = analyzeAllocationMessage(message.content);

  if (!analysis.shouldPrompt) return;

  await cleanupExpiredPendingAllocations();

  const pendingId = crypto.randomUUID();
  const createdAt = new Date().toISOString();
  const expiresAt = new Date(Date.now() + 15 * 60 * 1000).toISOString();

  await createPendingAllocation({
    pendingId,
    guildId: message.guild.id,
    channelId: message.channel.id,
    userId: message.author.id,
    username: message.member?.displayName || message.author.username,
    bottleName: analysis.bottleName,
    originalMessage: message.content,
    messageId: message.id,
    createdAt,
    expiresAt
  });

  await message.reply({
    embeds: [confirmationEmbed(analysis)],
    components: [confirmationRow(pendingId)],
    allowedMentions: { repliedUser: true }
  });
}
