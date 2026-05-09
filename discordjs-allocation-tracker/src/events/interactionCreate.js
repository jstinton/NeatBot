import { ActionRowBuilder, ButtonBuilder, ButtonStyle, EmbedBuilder, Events } from 'discord.js';
import { config } from '../config.js';
import {
  currentYear,
  deletePendingAllocation,
  getPendingAllocation,
  hasRecentDuplicate,
  saveAllocation
} from '../database.js';
import { updateLeaderboard } from '../services/leaderboard.js';

function disabledConfirmationRow(confirmed) {
  return new ActionRowBuilder().addComponents(
    new ButtonBuilder()
      .setCustomId('alloc_confirm_disabled')
      .setLabel(confirmed ? 'Confirmed' : 'Confirm')
      .setEmoji('✅')
      .setStyle(ButtonStyle.Success)
      .setDisabled(true),
    new ButtonBuilder()
      .setCustomId('alloc_cancel_disabled')
      .setLabel(confirmed ? 'Cancel' : 'Canceled')
      .setEmoji('❌')
      .setStyle(ButtonStyle.Secondary)
      .setDisabled(true)
  );
}

async function handleCommand(interaction) {
  const command = interaction.client.commands.get(interaction.commandName);

  if (!command) {
    await interaction.reply({ content: 'Unknown command.', ephemeral: true });
    return;
  }

  await command.execute(interaction);
}

async function handleAllocationButton(interaction) {
  const [action, pendingId] = interaction.customId.split(':');
  const pending = await getPendingAllocation(pendingId);

  if (!pending) {
    await interaction.reply({ content: 'That allocation confirmation expired. Post it again if you still want to log it.', ephemeral: true });
    return;
  }

  if (interaction.user.id !== pending.user_id) {
    await interaction.reply({ content: 'Only the original poster can confirm or cancel this allocation.', ephemeral: true });
    return;
  }

  if (action === 'alloc_cancel') {
    await deletePendingAllocation(pendingId);
    await interaction.update({
      embeds: [
        EmbedBuilder.from(interaction.message.embeds[0] ?? new EmbedBuilder())
          .setDescription(`Canceled logging **${pending.bottle_name}**.`)
          .setColor(0x777777)
      ],
      components: [disabledConfirmationRow(false)]
    });
    return;
  }

  const sinceIso = new Date(Date.now() - config.duplicateWindowHours * 60 * 60 * 1000).toISOString();
  const duplicate = await hasRecentDuplicate({
    guildId: pending.guild_id,
    userId: pending.user_id,
    bottleName: pending.bottle_name,
    sinceIso
  });

  if (duplicate) {
    await deletePendingAllocation(pendingId);
    await interaction.update({
      embeds: [
        EmbedBuilder.from(interaction.message.embeds[0] ?? new EmbedBuilder())
          .setDescription(`Duplicate protection kicked in. **${pending.bottle_name}** was already logged for you recently.`)
          .setColor(0xE67E22)
      ],
      components: [disabledConfirmationRow(false)]
    });
    return;
  }

  await saveAllocation({
    guildId: pending.guild_id,
    channelId: pending.channel_id,
    userId: pending.user_id,
    username: pending.username,
    bottleName: pending.bottle_name,
    originalMessage: pending.original_message,
    messageId: pending.message_id,
    createdAt: pending.created_at
  });
  await deletePendingAllocation(pendingId);

  await interaction.update({
    embeds: [
      EmbedBuilder.from(interaction.message.embeds[0] ?? new EmbedBuilder())
        .setDescription(`Logged **${pending.bottle_name}** for ${interaction.user}.`)
        .setColor(0x2ECC71)
    ],
    components: [disabledConfirmationRow(true)]
  });

  await updateLeaderboard(interaction.channel, currentYear(new Date(pending.created_at)));
  await interaction.followUp({ content: `Allocation logged: **${pending.bottle_name}**. Nice hunting.`, ephemeral: true });
}

export const name = Events.InteractionCreate;

export async function execute(interaction) {
  try {
    if (interaction.isChatInputCommand()) {
      await handleCommand(interaction);
      return;
    }

    if (interaction.isButton() && interaction.customId.startsWith('alloc_')) {
      await handleAllocationButton(interaction);
    }
  } catch (error) {
    console.error('Interaction handler failed:', error);

    const payload = { content: 'Something went sideways while handling that interaction.', ephemeral: true };

    if (interaction.deferred || interaction.replied) {
      await interaction.followUp(payload).catch(() => {});
    } else {
      await interaction.reply(payload).catch(() => {});
    }
  }
}
